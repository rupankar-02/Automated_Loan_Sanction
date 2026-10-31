import streamlit as st

from core.offers.catalog import get_catalog
from core.offers.models import OfferRun
from core.offers.run import compute_run
from core.offers.simulate import apply_changes, simulate
from core.utils.money import inr
from ui.pages import chat_panel
from ui.services import get_repo
from ui.steps import go_to

CHIP = {"eligible": "✅ Eligible", "eligible_reduced": "🟡 Eligible for less", "not_eligible": "❌ Not eligible",
        "needs_info": "❓ Needs info"}
SORTS = ["Best match", "Lowest EMI", "Highest amount"]


def _crit_line(c) -> str:
    icon = {"pass": "✔", "fail": "✖", "unknown": "❓"}[c.status]
    if c.status == "pass":
        return f"{icon} {c.label}"
    parts = f"{icon} **{c.label}**"
    if c.required is not None:
        parts += f": needs {c.required}, you have {c.actual}"
    if c.gap is not None:
        parts += f" (gap {c.gap:,})" if isinstance(c.gap, (int, float)) else ""
    if c.detail:
        parts += f" ({c.detail})"
    return parts


def _sort(evals, how: str):
    if how == "Lowest EMI":
        return sorted(evals, key=lambda e: (e.emi is None, e.emi or 0))
    if how == "Highest amount":
        return sorted(evals, key=lambda e: -(e.max_eligible_amount or 0))
    return sorted(evals, key=lambda e: (e.rank is None, e.rank or 0))


def _whatif(run: OfferRun) -> None:
    cat = get_catalog()
    lo, hi = cat.amount_bounds
    t = cat.inputs["tenure_months"]
    with st.expander("Try different numbers (instant, no AI)", expanded=False):
        c = st.columns(3)
        amt = c[0].slider("Loan amount (₹)", int(lo), int(hi), int(run.request.amount), step=10000)
        ten = c[1].slider("Tenure (months)", int(t["min"]), int(t["max"]), int(run.request.tenure_months), step=1)
        co = c[2].number_input("Co-applicant income per month (₹, what-if only)", min_value=0, value=0, step=5000)
        preview = simulate(run.facts, run.request, cat, amount=amt, tenure_months=ten, coapplicant_income=co)
        before = {e.offer_id: e for e in run.evaluations}
        changed = []
        for e in preview:
            old = before[e.offer_id]
            if e.status != old.status:
                name = cat.offer(e.offer_id).name
                at = f" at {inr(amt)}" if e.status in ("eligible", "eligible_reduced") else ""
                changed.append(f"**{name}** becomes {CHIP[e.status].split(' ', 1)[1].lower()}{at}")
        st.markdown("**What changes:** " + ("; ".join(changed) if changed else "no offer changes status."))
        st.dataframe([{"Offer": cat.offer(e.offer_id).name, "Status": CHIP[e.status],
                       "Max amount": inr(e.max_eligible_amount) if e.max_eligible_amount else "-",
                       "EMI": inr(e.emi) if e.emi else "-"} for e in preview], use_container_width=True, hide_index=True)
        if co:
            st.caption("Co-applicant income is a what-if only; a full co-applicant flow isn't part of this demo, so it isn't applied.")
        if st.button("Apply these values", disabled=(amt == run.request.amount and ten == run.request.tenure_months)):
            f, r = apply_changes(run.facts, run.request, amount=amt, tenure_months=ten)
            new = compute_run(f, r, cat)
            get_repo().save_run(st.session_state["app"].app_id, new, {"existing_emi": f.existing_emi, "credit_score": f.credit_score})
            get_repo().log(st.session_state["app"].app_id, "run_applied", run_id=new.run_id)
            st.session_state["run"] = new
            st.session_state["demo_defaults"] = {**st.session_state.get("demo_defaults", {}), "amount": amt, "tenure": ten}
            st.rerun()


def _card(app, run: OfferRun, e) -> None:
    cat = get_catalog()
    o = cat.offer(e.offer_id)
    with st.container(border=True):
        top = st.columns([3, 2])
        top[0].markdown(f"#### {o.name}  \n{o.lender}")
        top[1].markdown(f"### {CHIP[e.status]}" + (f"  \nRank {e.rank}: {e.rank_reason}" if e.rank else ""))
        if e.status in ("eligible", "eligible_reduced", "needs_info") and e.emi:
            m = st.columns(5)
            m[0].metric("Up to", inr(e.max_eligible_amount) if e.max_eligible_amount else "-")
            m[1].metric("Indicative rate", f"{e.indicative_rate_pct}%")
            label = "EMI for your amount" if e.evaluated_for == "requested" else f"EMI for {inr(e.evaluated_amount)}"
            m[2].metric(label, inr(e.emi))
            m[3].metric("Processing fee", inr(e.processing_fee))
            m[4].metric("Total cost", inr(e.total_cost))
            if e.status == "eligible_reduced":
                st.warning(f"You asked for {inr(run.request.amount)}, but the most this offer can give is {inr(e.max_eligible_amount)}.")
            if e.status == "needs_info":
                st.info("Add your credit score to see if you qualify (use *Edit my details*).")
        elif e.status == "not_eligible":
            st.error("; ".join(f"{c.label}: needs {c.required}, you have {c.actual}" for c in e.failed()[:2]) or "Not available.")
        with st.expander("Why / what's needed"):
            for c in e.criteria:
                st.markdown(_crit_line(c))
            sug = run.suggestions.get(e.offer_id, [])
            if sug:
                st.markdown("**What could change this**")
                for s in sug:
                    st.markdown(f"- {s.change}" + (f" _(trade-off: {s.trade_off})_" if s.trade_off else ""))
            st.caption(f"Terms: fee {o.processing_fee_pct}%, prepayment {o.prepayment_charge_pct}%, EMI limit {int(o.foir_cap * 100)}% of income.")
        if e.status in ("eligible", "eligible_reduced"):
            if st.button("Select this offer", key=f"sel_{e.offer_id}", type="primary"):
                get_repo().select_offer(app.app_id, e.offer_id, run.run_id)
                app.log("offer_selected", None, offer_id=e.offer_id)
                go_to("kyc")


def render(model_key: str) -> None:
    app = st.session_state["app"]
    run: OfferRun | None = st.session_state.get("run")
    if run is None:
        go_to("extra_inputs")
        return
    st.header("Your loan offers")
    st.warning("**Indicative offers** based on your documents and the details you entered. Not a loan approval. "
               "Subject to lender verification and credit bureau checks. Sample lenders and assumed policies; not real products.")
    r = run.request
    st.markdown(f"For **{inr(r.amount)}** over **{r.tenure_months} months**, with monthly income **{inr(run.facts.net_monthly_income)}** "
                f"and existing EMIs **{inr(run.facts.existing_emi)}**.")
    if run.facts.income_variation_warning:
        st.caption("Your net pay varied by more than 15% between salary slips, so we used the average.")
    c = st.columns([1, 1, 3])
    if c[0].button("Edit my details"):
        go_to("extra_inputs")
    sort = c[1].selectbox("Sort by", SORTS, label_visibility="collapsed")

    _whatif(run)
    for e in _sort(run.evaluations, sort):
        _card(app, run, e)

    st.divider()
    chat_panel.render(app, run, model_key)
