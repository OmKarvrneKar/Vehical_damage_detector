"""Matplotlib analytics charts for damage reports (user or admin scoped)."""
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SEV_COLORS = {"Minor": "#1f8a5b", "Moderate": "#e8710a", "Severe": "#d62839", "None": "#5d6b85"}
GREY = "#5d6b85"


def summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "total": 0,
            "damaged": 0,
            "top_type": "-",
            "avg_confidence": 0,
            "avg_cost": 0,
            "severity": {"Minor": 0, "Moderate": 0, "Severe": 0, "None": 0}
        }

    dmg = df[df["Damage Detected"] == "Yes"]
    types_series = dmg["Damage Type"].dropna().str.split(", ").explode()
    types_series = types_series[types_series != "-"]
    types = types_series.value_counts() if not types_series.empty else pd.Series(dtype=int)

    conf_vals = df["Confidence (%)"].dropna()
    avg_conf = round(float(conf_vals.mean()), 1) if not conf_vals.empty else 0

    cost_vals = dmg["Cost Max (INR)"].dropna()
    avg_cost = int(cost_vals.mean()) if not cost_vals.empty else 0

    sev_counts = dmg["Severity Level"].value_counts().to_dict()

    return {
        "total": int(len(df)),
        "damaged": int(len(dmg)),
        "top_type": types.index[0] if len(types) else "-",
        "avg_confidence": avg_conf,
        "avg_cost": avg_cost,
        "severity": {
            "Minor": int(sev_counts.get("Minor", 0)),
            "Moderate": int(sev_counts.get("Moderate", 0)),
            "Severe": int(sev_counts.get("Severe", 0)),
            "None": int(len(df) - len(dmg))
        }
    }


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, transparent=True, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _empty(msg):
    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.axis("off")
    ax.text(0.5, 0.5, msg, ha="center", va="center", color=GREY, fontsize=12)
    return _png(fig)


def make_chart(name: str, df: pd.DataFrame) -> bytes:
    if df.empty:
        return _empty("No reports available yet")

    dmg = df[df["Damage Detected"] == "Yes"]
    if dmg.empty and name != "trend":
        return _empty("No damage detected in reports yet")

    fig, ax = plt.subplots(figsize=(6, 3.8))

    if name == "types":
        types_series = dmg["Damage Type"].dropna().str.split(", ").explode()
        types_series = types_series[types_series != "-"]
        if types_series.empty:
            plt.close(fig)
            return _empty("No damage types recorded yet")
        c = types_series.value_counts().sort_values()
        ax.barh(c.index, c.values, color="#f2a900")
        ax.set_title("Damage Type Frequency", color="#14213d", fontweight="bold")
        ax.set_xlabel("Occurrences", color=GREY)

    elif name == "severity":
        c = dmg["Severity Level"].value_counts()
        if c.empty:
            plt.close(fig)
            return _empty("No severity data available yet")
        colors = [SEV_COLORS.get(k, GREY) for k in c.index]
        ax.pie(c.values, labels=c.index, autopct="%1.0f%%", colors=colors,
               wedgeprops={"width": 0.45}, textprops={"color": "#14213d", "fontweight": "bold"})
        ax.set_title("Severity Distribution", color="#14213d", fontweight="bold")

    else:  # trend
        if dmg.empty:
            plt.close(fig)
            return _empty("No trend data available yet")
        d = dmg.assign(Day=dmg["Timestamp"].astype(str).str[:10])
        t = d.groupby(["Day", "Severity Level"]).size().unstack(fill_value=0)
        t.plot(kind="bar", stacked=True, ax=ax, color=[SEV_COLORS.get(c, GREY) for c in t.columns])
        ax.set_title("Reports Over Time by Severity", color="#14213d", fontweight="bold")
        ax.set_xlabel("", color=GREY)
        ax.legend(frameon=False)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")

    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=GREY)
    return _png(fig)
