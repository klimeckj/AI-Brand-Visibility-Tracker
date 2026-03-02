import streamlit as st
import requests
import io
import csv
import pandas as pd
from datetime import datetime

st.set_page_config(
    page_title="AI Visibility Tracker",
    page_icon="🔍",
    layout="wide",
)

# ── Config ────────────────────────────────────────────────────────────────────
try:
    N8N_WEBHOOK_URL = st.secrets["n8n_webhook_url"]
    API_KEY = st.secrets["gemini_api_key"]
except KeyError:
    st.error("Missing secrets. Add n8n_webhook_url and gemini_api_key to .streamlit/secrets.toml (local) or Streamlit Cloud secrets.")
    st.stop()

# ── Session state ────────────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = []
if "selected_index" not in st.session_state:
    st.session_state.selected_index = None
if "query_success" not in st.session_state:
    st.session_state.query_success = False

# ── Sidebar — Brand Setup ─────────────────────────────────────────────────────
with st.sidebar:
    st.header("🏢 Brand Setup")
    brand = st.text_input("Brand name", value="Tesla")
    brand_url = st.text_input("Website URL (optional)", placeholder="https://www.tesla.com/")
    brand_description = st.text_area(
        "Business description (optional)",
        placeholder="Short description of what your company does and who your customers are.",
        height=100,
    )
    st.divider()
    st.caption("These details are saved with each result for context.")


# ── Helper: render a single result detail ────────────────────────────────────
def render_result_detail(r: dict):
    metrics = r.get("metrics", {})
    is_visible = metrics.get("is_visible", False)
    sentiment = metrics.get("sentiment", "UNKNOWN")
    context = metrics.get("context", "No context provided.")
    competitors = metrics.get("competitors", [])
    unbiased_response = r.get("unbiased_bot_response", "")

    if is_visible:
        st.success(f"✅ **{r['brand']}** is mentioned!")
    else:
        st.warning(f"❌ **{r['brand']}** is NOT mentioned.")

    st.markdown("#### Visibility Metrics")
    total_mentioned = len(competitors) + (1 if is_visible else 0)
    visibility_score = f"1 / {total_mentioned}" if is_visible and total_mentioned > 0 else "0"

    col1, col2, col3 = st.columns(3)
    with col1:
        sentiment_labels = {
            "POSITIVE": "🟢 Positive",
            "NEGATIVE": "🔴 Negative",
            "NEUTRAL": "⚪ Neutral",
            "NONE": "⬜ Not mentioned",
        }
        st.metric("Sentiment", sentiment_labels.get(sentiment, sentiment))
    with col2:
        st.metric("Competitors Mentioned", len(competitors))
    with col3:
        st.metric(
            "Visibility Score",
            visibility_score,
            help="1 / N means brand appeared once among N total brands mentioned.",
        )

    st.markdown("**How it fits into the answer:**")
    st.info(context)

    if competitors:
        st.markdown("**Competitors explicitly named:**")
        st.write(", ".join(competitors))

    st.markdown("---")
    st.markdown("#### What the AI actually said")
    st.markdown("> *Raw, unbiased LLM response — before analysis.*")
    st.markdown(unbiased_response if unbiased_response else "*(No response captured.)*")

    with st.expander("View Raw JSON from n8n"):
        st.json(r.get("raw_data", {}))


# ── Helper: build CSV bytes from session results ──────────────────────────────
def results_to_csv(results: list) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Brand", "Prompt", "Prompt Type", "Visible", "Sentiment", "Competitors", "Context"])
    for r in results:
        metrics = r.get("metrics", {})
        writer.writerow([
            r.get("timestamp", ""),
            r.get("brand", ""),
            r.get("prompt", ""),
            r.get("prompt_type", ""),
            metrics.get("is_visible", False),
            metrics.get("sentiment", ""),
            ", ".join(metrics.get("competitors", [])),
            metrics.get("context", ""),
        ])
    return output.getvalue().encode("utf-8")


# ── Core query function (shared by New Query form and Force Rerun) ────────────
def run_query(brand: str, prompt: str, prompt_type: str, brand_url: str, brand_description: str):
    """Call n8n, append result to session state + disk. Returns True on success."""
    payload = {"brand": brand, "prompt": prompt, "api_key": API_KEY, "brand_description": brand_description}
    try:
        response = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "brand": brand,
                "brand_url": brand_url,
                "brand_description": brand_description,
                "prompt": prompt,
                "prompt_type": prompt_type,
                "metrics": data.get("metrics", {}),
                "unbiased_bot_response": data.get("unbiased_bot_response", ""),
                "raw_data": data,
            }
            st.session_state.results.append(record)
            st.session_state.selected_index = len(st.session_state.results) - 1
            return True
        else:
            st.error(f"Error {response.status_code} from n8n: {response.text}")
            return False
    except requests.exceptions.Timeout:
        st.error("⏱️ Request timed out (30s). Is your n8n instance running?")
        return False
    except Exception as e:
        st.error(f"Failed to connect to n8n: {e}")
        return False


# ── Main UI ───────────────────────────────────────────────────────────────────
st.title("AI Brand Visibility Tracker")
st.markdown("**Evaluating how LLMs represent your brand.**")

tab_new, tab_dashboard, tab_trends = st.tabs(["➕ New Query", "📊 Dashboard", "📈 Trends"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — New Query
# ═══════════════════════════════════════════════════════════════════════════════
with tab_new:
    prompt_type = st.selectbox(
        "Prompt type",
        ["Informational", "Commercial", "Competitor", "Navigational"],
        help="Label to categorize the intent of this prompt.",
    )
    prompt = st.text_area(
        "Prompt to ask the LLM:",
        value="What are the best electric car brands?",
    )

    if st.button("Check Visibility", type="primary"):
        st.session_state.query_success = False
        if not brand.strip():
            st.warning("Please enter a brand name in the sidebar.")
            st.stop()
        if not prompt.strip():
            st.warning("Please enter a prompt.")
            st.stop()
        if not API_KEY or API_KEY == "YOUR_GEMINI_API_KEY_HERE":
            st.error("Please add a valid Gemini API Key to your Streamlit secrets.")
            st.stop()

        with st.spinner("Analyzing LLM response…"):
            ok = run_query(brand, prompt, prompt_type, brand_url, brand_description)
            if ok:
                st.session_state.query_success = True

    if st.session_state.query_success:
        st.success("✅ Analysis complete — check the **Dashboard** tab for results.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Dashboard
# ═══════════════════════════════════════════════════════════════════════════════
with tab_dashboard:
    if not st.session_state.results:
        st.info("No results yet. Run your first query in the **New Query** tab.")
    else:
        results = st.session_state.results

        # ── Summary metrics ───────────────────────────────────────────────────
        total_runs = len(results)
        visible_count = sum(1 for r in results if r.get("metrics", {}).get("is_visible"))
        visibility_rate = f"{visible_count / total_runs * 100:.0f}%"

        sentiments = [r.get("metrics", {}).get("sentiment", "") for r in results if r.get("metrics", {}).get("is_visible")]
        dominant_sentiment = max(set(sentiments), key=sentiments.count) if sentiments else "N/A"
        sentiment_labels = {"POSITIVE": "🟢 Positive", "NEGATIVE": "🔴 Negative", "NEUTRAL": "⚪ Neutral", "NONE": "⬜ None"}

        all_competitors = set()
        for r in results:
            all_competitors.update(r.get("metrics", {}).get("competitors", []))

        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("Total Runs", total_runs)
        sm2.metric("Visibility Rate", visibility_rate, help="Share of prompts where the brand was mentioned")
        sm3.metric("Dominant Sentiment", sentiment_labels.get(dominant_sentiment, dominant_sentiment))
        sm4.metric("Unique Competitors Seen", len(all_competitors))

        st.markdown("---")

        # ── Results table ─────────────────────────────────────────────────────
        table_rows = []
        for r in reversed(results):
            metrics = r.get("metrics", {})
            table_rows.append({
                "Time": r.get("timestamp", ""),
                "Brand": r.get("brand", ""),
                "Prompt": r.get("prompt", "")[:60] + ("…" if len(r.get("prompt", "")) > 60 else ""),
                "Type": r.get("prompt_type", ""),
                "Visible": "✅" if metrics.get("is_visible") else "❌",
                "Sentiment": metrics.get("sentiment", ""),
                "Competitors #": len(metrics.get("competitors", [])),
            })

        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        col_export, col_select = st.columns([1, 3])
        with col_export:
            st.download_button(
                label="⬇️ Export CSV",
                data=results_to_csv(results),
                file_name=f"visibility_{brand}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
            )
        with col_select:
            labels = [
                f"{r['timestamp']}  |  {r['prompt'][:55]}…"
                if len(r["prompt"]) > 55
                else f"{r['timestamp']}  |  {r['prompt']}"
                for r in reversed(results)
            ]
            chosen_label = st.selectbox("View detail for a result:", labels)
            chosen_index = len(results) - 1 - labels.index(chosen_label)
            st.session_state.selected_index = chosen_index

        # ── Result detail ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🔍 Result Detail")
        r = results[st.session_state.selected_index]
        render_result_detail(r)

        # Force Rerun button
        if st.button("🔄 Force Rerun this prompt", help="Re-submit the same prompt and append a fresh result"):
            with st.spinner("Re-running…"):
                ok = run_query(
                    r["brand"], r["prompt"], r.get("prompt_type", "Informational"),
                    r.get("brand_url", ""), r.get("brand_description", ""),
                )
                if ok:
                    st.success("✅ Rerun complete — new result appended.")
                    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Trends
# ═══════════════════════════════════════════════════════════════════════════════
with tab_trends:
    if not st.session_state.results:
        st.info("No results yet. Run your first query in the **New Query** tab.")
    else:
        results = st.session_state.results

        # ── Summary across all history ────────────────────────────────────────
        st.markdown("#### Overall Visibility Over Time")
        df_all = pd.DataFrame([
            {
                "timestamp": pd.to_datetime(r["timestamp"]),
                "visible": 1 if r.get("metrics", {}).get("is_visible") else 0,
            }
            for r in results
        ]).set_index("timestamp").sort_index()

        st.line_chart(df_all["visible"], use_container_width=True,
                      color="#00c0a3")
        st.caption("1 = brand mentioned, 0 = brand not mentioned. Each point is one query run.")

        st.markdown("---")
        st.markdown("#### Visibility Trend per Prompt")

        # Build unique prompt list
        unique_prompts = list(dict.fromkeys(r["prompt"] for r in results))
        selected_prompt = st.selectbox(
            "Select a prompt to track:",
            unique_prompts,
            format_func=lambda p: p[:80] + "…" if len(p) > 80 else p,
        )

        prompt_runs = [r for r in results if r["prompt"] == selected_prompt]

        if len(prompt_runs) < 2:
            st.info("Run this prompt at least twice (use **Force Rerun** in Dashboard) to see a trend.")
        else:
            df_prompt = pd.DataFrame([
                {
                    "timestamp": pd.to_datetime(r["timestamp"]),
                    "visible": 1 if r.get("metrics", {}).get("is_visible") else 0,
                }
                for r in prompt_runs
            ]).set_index("timestamp").sort_index()

            st.line_chart(df_prompt["visible"], use_container_width=True, color="#ff6347")
            st.caption(f"{len(prompt_runs)} runs tracked for this prompt.")

        st.markdown("---")
        st.markdown("#### Sentiment Distribution")

        sentiment_counts = {}
        for r in results:
            s = r.get("metrics", {}).get("sentiment", "UNKNOWN")
            sentiment_counts[s] = sentiment_counts.get(s, 0) + 1

        df_sentiment = pd.DataFrame(
            list(sentiment_counts.items()), columns=["Sentiment", "Count"]
        ).set_index("Sentiment")
        st.bar_chart(df_sentiment["Count"], use_container_width=True)
