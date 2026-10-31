"""Chat beside the offers. One model call per message, verified; the template answer is the safety net."""
import json

import streamlit as st

from core.chat.answer import RECALC_NOTE, answer
from core.chat.context import build_context, context_json, estimate_tokens
from core.chat.guards import detect_language
from core.chat.llm import FakeLLM, get_chat_llm
from core.config.settings import get_settings
from ui.services import get_repo


def _no_llm(*_):
    raise RuntimeError("template-only mode")


def _greeting(run) -> str:
    n = run.facts.first_name or "there"
    ok = sum(1 for e in run.evaluations if e.status in ("eligible", "eligible_reduced"))
    return (f"Hi {n}! I can explain your loan offers in simple words. Right now {ok} of {len(run.evaluations)} offers are open to you. "
            "These are indicative, not an approval. What would you like to know?")


def _init(app, run, repo) -> dict:
    chat = st.session_state.get("chat")
    if chat is None or chat["app_id"] != app.app_id:
        sid = repo.create_chat_session(app.app_id)
        chat = {"app_id": app.app_id, "session_id": sid, "run_id": run.run_id, "msgs": []}
        _add(chat, repo, "assistant", _greeting(run), run.run_id, "passed")
        st.session_state["chat"] = chat
    elif chat["run_id"] != run.run_id:                      # the user applied new numbers
        _add(chat, repo, "system_note", RECALC_NOTE, run.run_id)
        chat["run_id"] = run.run_id
    return chat


def _add(chat, repo, role, content, run_id, verification=None, ctx_hash=None) -> dict:
    mid = repo.add_message(chat["session_id"], role, content, run_id, ctx_hash, verification)
    msg = {"id": mid, "role": role, "content": content, "verification": verification, "feedback": None}
    chat["msgs"].append(msg)
    return msg


def _chips(run) -> list[str]:
    chips = []
    hard = [e for e in run.evaluations if e.status == "not_eligible"]
    if hard:
        from core.offers.catalog import get_catalog
        chips.append(f"Why wasn't I offered {get_catalog().offer(hard[-1].offer_id).name.split()[0]}?")
    chips.append("How can I get a lower rate?")
    if sum(1 for e in run.evaluations if e.rank) >= 2:
        chips.append("Which offer is cheaper?")
    chips.append("What is FOIR?")
    return chips[:4]


def _ask(chat, repo, run, ctx, question: str, model_key: str) -> None:
    user_count = sum(1 for m in chat["msgs"] if m["role"] == "user")
    _add(chat, repo, "user", question, run.run_id)
    lang = detect_language(question)
    llm = FakeLLM(_no_llm) if get_settings().use_mock_vlm else get_chat_llm(lang, model_key)
    history = [(m["role"], m["content"]) for m in chat["msgs"][:-1]]
    with st.spinner("Thinking..."):
        res = answer(question, ctx, history, llm, user_count)
    if res.verification == "fallback_template":
        repo.log(chat["app_id"], "chat_fallback", run_id=run.run_id)
    elif res.verification == "blocked":
        repo.log(chat["app_id"], "chat_blocked", run_id=run.run_id)
    _add(chat, repo, "assistant", res.text, run.run_id, res.verification, res.context_hash)


def render(app, run, model_key: str) -> None:
    repo = get_repo()
    ctx = build_context(run)
    chat = _init(app, run, repo)

    st.subheader("Ask about your offers")
    pending = None
    cols = st.columns(len(_chips(run)))
    for col, chip in zip(cols, _chips(run)):
        if col.button(chip, key=f"chip_{chip}", use_container_width=True):
            pending = chip

    for m in chat["msgs"]:
        if m["role"] == "system_note":
            st.caption(f"ℹ️ {m['content']}")
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m["role"] == "assistant":
                if m["verification"] == "fallback_template":
                    st.caption("Answered from fixed rules because the assistant couldn't be verified.")
                fb = st.columns([1, 1, 8])
                if fb[0].button("👍", key=f"up_{m['id']}"):
                    repo.set_feedback(m["id"], 1); m["feedback"] = 1
                if fb[1].button("👎", key=f"dn_{m['id']}"):
                    repo.set_feedback(m["id"], -1); m["feedback"] = -1

    typed = st.chat_input("Ask about an offer, why one isn't available, or what you can change")
    question = pending or typed
    if question:
        _ask(chat, repo, run, ctx, question, model_key)
        st.rerun()

    with st.expander("What the assistant can see"):
        cj = context_json(ctx)
        st.caption(f"The exact, masked context sent with every message (about {estimate_tokens(cj):,} tokens). "
                   "It never contains your PAN, Aadhaar, account number, surname or document text.")
        st.code(json.dumps(ctx, indent=1, ensure_ascii=False), language="json")
