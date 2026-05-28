import streamlit as st
from datetime import date, datetime, timedelta
import calendar
import pandas as pd
from io import BytesIO
import uuid
from supabase import create_client, Client

st.set_page_config(page_title="Registo de Tempo", page_icon="⏱", layout="wide")

# ════════════════════════════════════════════════════════════════════════════
# SUPABASE CLIENT
# Requer .streamlit/secrets.toml com:
#   SUPABASE_URL = "https://xxxx.supabase.co"
#   SUPABASE_KEY = "eyJ..."
# ════════════════════════════════════════════════════════════════════════════

@st.cache_resource
def init_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

sb = init_supabase()

# ═════════════════════════════════════════════
# AUTH
# ═════════════════════════════════════════════

if "user" not in st.session_state:
    st.session_state.user = None

def sign_in(email, password):
    try:
        res = sb.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        st.session_state.user = res.user
        st.rerun()
    except Exception as e:
        st.error("Login inválido")

def sign_up(email, password):
    try:
        sb.auth.sign_up({
            "email": email,
            "password": password
        })
        st.success("Conta criada. Faz login.")
    except Exception as e:
        st.error(str(e))

def logout():
    sb.auth.sign_out()
    st.session_state.user = None
    st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# UTILITY
# ════════════════════════════════════════════════════════════════════════════

def uid():
    return str(uuid.uuid4())[:8]

def today_key():
    return date.today().isoformat()

def fmt_time(minutes):
    minutes = int(minutes)
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}h{minutes % 60:02d}m"

# ════════════════════════════════════════════════════════════════════════════
# CARREGAR DADOS DO SUPABASE
# Reconstrói a mesma estrutura de dicionário usada anteriormente
# ════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=2)
def load_data() -> dict:
    # --- Perfis ---
    profiles = (sb.table("profiles").select("*").execute().data) or []

    # Seed perfil por defeito se vazio
    if not profiles:
        default = {"id": "p1", "name": "O meu perfil", "hours": 7.5}
        sb.table("profiles").insert(default).execute()
        profiles = [default]

    # --- Perfil ativo ---
    setting = sb.table("app_settings").select("value").eq("key", "active_profile").execute().data
    active_profile = setting[0]["value"] if setting else profiles[0]["id"]

    # Garante que existe a entrada em app_settings
    if not setting:
        sb.table("app_settings").upsert({"key": "active_profile", "value": active_profile}).execute()

    # --- Tipos de task ---
    types_rows = (sb.table("task_types").select("name").order("sort_order").execute().data) or []
    task_types = [r["name"] for r in types_rows]

    # Seed tipos por defeito se vazio
    if not task_types:
        defaults = ["Reunião", "Desenvolvimento", "Suporte", "Documentação",
                    "Email", "Revisão", "Planeamento", "Outro"]
        sb.table("task_types").insert(
            [{"name": n, "sort_order": i} for i, n in enumerate(defaults)]
        ).execute()
        task_types = defaults

    # --- Tasks → estrutura days[profile_id][date_str] = {tasks: [...]} ---
    tasks_rows = (sb.table("tasks").select("*").execute().data) or []

    days: dict = {}
    for t in tasks_rows:
        pid = t["profile_id"]
        day_key = t["date"] if isinstance(t["date"], str) else t["date"].isoformat()
        days.setdefault(pid, {}).setdefault(day_key, {"tasks": []})
        days[pid][day_key]["tasks"].append({
            "id":       t["id"],
            "name":     t["name"],
            "type":     t.get("type") or "",
            "ticket":   t.get("ticket") or "",
            "minutes":  t["minutes"],
            "addedAt":  t.get("added_at") or "",
        })

    return {
        "profiles":       profiles,
        "active_profile": active_profile,
        "days":           days,
        "task_types":     task_types,
    }

def invalidate():
    """Invalida a cache após qualquer mutação."""
    load_data.clear()

# ════════════════════════════════════════════════════════════════════════════
# MUTAÇÕES — substituem os save_data(data) do código original
# ════════════════════════════════════════════════════════════════════════════

def db_set_active_profile(profile_id: str):
    sb.table("app_settings").upsert({"key": "active_profile", "value": profile_id}).execute()
    invalidate()

def db_add_task(profile_id: str, day_key: str, task: dict):
    sb.table("tasks").insert({
        "user_id": st.session_state.user.id,
        "id": task["id"],
        "profile_id": profile_id,
        "date": day_key,
        "name": task["name"],
        "type": task.get("type", ""),
        "ticket": task.get("ticket", ""),
        "minutes": task["minutes"],
        "added_at": task.get("addedAt", ""),
    }).execute()
    invalidate()

def db_update_task(task_id: str, name: str, task_type: str, ticket: str, minutes: int):
    sb.table("tasks").update({
        "name":    name,
        "type":    task_type,
        "ticket":  ticket,
        "minutes": minutes,
    }).eq("id", task_id).execute()
    invalidate()

def db_delete_task(task_id: str):
    sb.table("tasks").delete().eq("id", task_id).execute()
    invalidate()

def db_delete_day(profile_id: str, day_key: str):
    sb.table("tasks").delete().eq("profile_id", profile_id).eq("date", day_key).execute()
    invalidate()

def db_add_profile(name: str, hours: float):
    sb.table("profiles").insert({"id": uid(), "name": name, "hours": hours}).execute()
    invalidate()

def db_delete_profile(profile_id: str):
    sb.table("profiles").delete().eq("id", profile_id).execute()
    invalidate()

def db_add_task_type(name: str):
    max_order_res = (sb.table("task_types").select("sort_order")
                       .order("sort_order", desc=True).limit(1).execute().data)
    next_order = (max_order_res[0]["sort_order"] + 1) if max_order_res else 0
    sb.table("task_types").insert({"name": name, "sort_order": next_order}).execute()
    invalidate()

def db_delete_task_type(name: str):
    sb.table("task_types").delete().eq("name", name).execute()
    invalidate()

# ════════════════════════════════════════════════════════════════════════════
# HELPERS (mesma lógica de antes, sem I/O)
# ════════════════════════════════════════════════════════════════════════════

def get_day(data, profile_id, day_key):
    data["days"].setdefault(profile_id, {}).setdefault(day_key, {"tasks": []})
    return data["days"][profile_id][day_key]

def total_logged(data, profile_id, day_key):
    return sum(t["minutes"] for t in get_day(data, profile_id, day_key)["tasks"])

def get_days_with_tasks(data, profile_id):
    if profile_id not in data["days"]:
        return set()
    return {k for k, v in data["days"][profile_id].items() if v["tasks"]}

def export_to_excel(data, profile_id):
    if profile_id not in data["days"]:
        return None
    rows = []
    for day_key, day_data in sorted(data["days"][profile_id].items()):
        for task in day_data["tasks"]:
            rows.append({
                "Data": day_key,
                "Task": task["name"],
                "Tipo": task.get("type", "N/A"),
                "Ticket CSI": task.get("ticket", ""),
                "Horas": task["minutes"] // 60,
                "Minutos": task["minutes"] % 60,
                "Total (min)": task["minutes"],
                "Adicionado às": task.get("addedAt", ""),
            })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Tasks")
        ws = writer.sheets["Tasks"]
        for idx, col in enumerate(df.columns):
            ws.column_dimensions[chr(65 + idx)].width = (
                max(df[col].astype(str).apply(len).max(), len(col)) + 2
            )
    return output.getvalue()

def get_stats_by_type(data, profile_id, start_date=None, end_date=None):
    if profile_id not in data["days"]:
        return {}
    stats: dict = {}
    for day_key, day_data in data["days"][profile_id].items():
        if start_date and day_key < start_date:
            continue
        if end_date and day_key > end_date:
            continue
        for task in day_data["tasks"]:
            tt = task.get("type") or "Sem tipo"
            stats.setdefault(tt, {"count": 0, "minutes": 0})
            stats[tt]["count"] += 1
            stats[tt]["minutes"] += task["minutes"]
    return stats

def get_weekly_stats(data, profile_id, weeks=4):
    today = date.today()
    result = []
    for i in range(weeks):
        ws = today - timedelta(days=today.weekday() + 7 * i)
        we = ws + timedelta(days=6)
        total = 0
        if profile_id in data["days"]:
            for day_key, day_data in data["days"][profile_id].items():
                d = datetime.fromisoformat(day_key).date()
                if ws <= d <= we:
                    total += sum(t["minutes"] for t in day_data["tasks"])
        result.append({"week": f"{ws.strftime('%d/%m')} - {we.strftime('%d/%m')}", "minutes": total})
    return list(reversed(result))

# ════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ════════════════════════════════════════════════════════════════════════════

defaults = {
    "timer_running": False,
    "timer_start": None,
    "timer_elapsed": 0,
    "timer_task": "",
    "timer_ticket": "",
    "timer_type": None,
    "selected_date": today_key(),
    "view_month": date.today().replace(day=1),
    "current_page": "Registo",
    "edit_task": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ════════════════════════════════════════════════════════════════════════════
# STYLES
# ════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stat-box { background:#f8f9fa; border-radius:10px; padding:1rem 1.2rem; margin-bottom:0; }
.stat-label { font-size:12px; color:#888; margin-bottom:2px; }
.stat-value { font-size:22px; font-weight:600; }
.green { color:#3B6D11; } .red { color:#A32D2D; }
.amber { color:#BA7517; } .blue { color:#185FA5; }
.timer-display { font-size:52px; font-weight:600; text-align:center;
    font-variant-numeric:tabular-nums; letter-spacing:3px; padding:1rem 0 0.5rem; }
.badge { display:inline-block; background:#E6F1FB; color:#0C447C;
    border-radius:10px; padding:2px 8px; font-size:11px; font-weight:500; }
.section-title { font-size:11px; font-weight:600; color:#999;
    text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.75rem; }
div[data-testid="stForm"] { border:none !important; padding:0 !important; }
</style>
""", unsafe_allow_html=True)

# ═════════════════════════════════════════════
# LOGIN SCREEN
# ═════════════════════════════════════════════

if not st.session_state.user:

    st.title("🔐 Login")

    tab1, tab2 = st.tabs(["Entrar", "Criar conta"])

    with tab1:
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")

        if st.button("Entrar"):
            sign_in(email, password)

    with tab2:
        new_email = st.text_input("Novo email")
        new_password = st.text_input("Nova password", type="password")

        if st.button("Criar conta"):
            sign_up(new_email, new_password)

    st.stop()

# ════════════════════════════════════════════════════════════════════════════
# CARREGAR DADOS
# ════════════════════════════════════════════════════════════════════════════

data = load_data()

# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## ⏱ Time Tracker")
    st.divider()

    pages = ["📊 Dashboard", "✏️ Registo", "📅 Histórico", "⚙️ Configurações"]
    selected = st.radio("Navegação", pages, label_visibility="collapsed")
    st.session_state.current_page = selected.split(" ", 1)[1]

    st.divider()

    prof_names = [p["name"] for p in data["profiles"]]
    active_idx = next((i for i, p in enumerate(data["profiles"]) if p["id"] == data["active_profile"]), 0)
    chosen = st.selectbox("Perfil ativo", prof_names, index=active_idx)
    chosen_prof = next(p for p in data["profiles"] if p["name"] == chosen)

    if chosen_prof["id"] != data["active_profile"]:
        db_set_active_profile(chosen_prof["id"])
        st.rerun()

    prof = chosen_prof

    st.divider()
    if st.button("🚪 Logout", use_container_width=True):
        logout()
    st.caption(f"📅 {today_key()}")

# ════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

def render_dashboard():
    st.markdown("## 📊 Dashboard")

    period_col1, period_col2 = st.columns([2, 1])
    with period_col1:
        period = st.selectbox("Período", ["Últimos 7 dias", "Últimas 4 semanas", "Último mês", "Tudo"], index=1)
    with period_col2:
        excel_data = export_to_excel(data, prof["id"])
        if excel_data:
            st.download_button("📥 Exportar Excel", data=excel_data,
                file_name=f"tasks_{prof['name']}_{today_key()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.divider()

    end_date = today_key()
    if period == "Últimos 7 dias":
        start_date = (date.today() - timedelta(days=7)).isoformat()
    elif period == "Últimas 4 semanas":
        start_date = (date.today() - timedelta(days=28)).isoformat()
    elif period == "Último mês":
        start_date = date.today().replace(day=1).isoformat()
    else:
        start_date = None

    type_stats = get_stats_by_type(data, prof["id"], start_date, end_date)

    if not type_stats:
        st.info("Sem dados para o período selecionado.")
        return

    total_tasks = sum(s["count"] for s in type_stats.values())
    total_hours = sum(s["minutes"] for s in type_stats.values()) / 60

    c1, c2, c3 = st.columns(3)
    c1.metric("Total de Tasks", total_tasks)
    c2.metric("Total de Horas", f"{total_hours:.1f}h")
    c3.metric("Média/Dia", f"{total_hours / 7:.1f}h" if period == "Últimos 7 dias" else f"{total_hours / 28:.1f}h")

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### Distribuição por Tipo")
        chart_data = pd.DataFrame([
            {"Tipo": tipo, "Horas": stats["minutes"] / 60}
            for tipo, stats in sorted(type_stats.items(), key=lambda x: x[1]["minutes"], reverse=True)
        ])
        if not chart_data.empty:
            st.bar_chart(chart_data.set_index("Tipo"))
        st.markdown("### Detalhes por Tipo")
        for tipo, stats in sorted(type_stats.items(), key=lambda x: x[1]["minutes"], reverse=True):
            st.markdown(f"**{tipo}**: {stats['count']} tasks · {fmt_time(stats['minutes'])}")

    with col_right:
        st.markdown("### Evolução Semanal")
        weekly = get_weekly_stats(data, prof["id"], 4)
        if weekly:
            weekly_df = pd.DataFrame([{"Semana": w["week"], "Horas": w["minutes"] / 60} for w in weekly])
            st.line_chart(weekly_df.set_index("Semana"))

        st.markdown("### Eficiência")
        days_with_data = len(get_days_with_tasks(data, prof["id"]))
        if start_date:
            period_days = (date.today() - datetime.fromisoformat(start_date).date()).days + 1
        else:
            period_days = days_with_data

        if period_days > 0:
            coverage = (days_with_data / period_days * 100) if period != "Tudo" else 100
            st.metric("Dias registados", f"{days_with_data}/{period_days}", f"{coverage:.0f}%")

        avg = total_hours / days_with_data if days_with_data > 0 else 0
        st.metric("Média por dia de trabalho", f"{avg:.1f}h")
        st.metric("Taxa de registo", f"{avg / prof['hours'] * 100:.0f}%" if prof["hours"] > 0 else "—")

# ════════════════════════════════════════════════════════════════════════════
# PAGE: REGISTO
# ════════════════════════════════════════════════════════════════════════════

def render_registo():
    st.markdown("## ✏️ Registo de Tempo")

    today = today_key()
    logged = total_logged(data, prof["id"], today)
    bank = int(prof["hours"] * 60)
    remaining = bank - logged
    pct = min(100, int(logged / bank * 100)) if bank > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>Carga diária</div>"
                    f"<div class='stat-value blue'>{prof['hours']}h</div></div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"<div class='stat-box'><div class='stat-label'>Registado</div>"
                    f"<div class='stat-value green'>{fmt_time(logged)}</div></div>", unsafe_allow_html=True)
        st.progress(pct / 100)
    with c3:
        lbl = "Banco restante" if remaining >= 0 else "Excedido"
        st.markdown(f"<div class='stat-box'><div class='stat-label'>{lbl}</div>"
                    f"<div class='stat-value amber'>{fmt_time(abs(remaining))}</div></div>", unsafe_allow_html=True)
    with c4:
        waste = remaining if remaining > 0 else 0
        color = "red" if waste > 0 else "green"
        st.markdown(f"<div class='stat-box'><div class='stat-label'>Desperdício</div>"
                    f"<div class='stat-value {color}'>{fmt_time(waste) if waste > 0 else '0h00m'}</div></div>",
                    unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    left, right = st.columns([1, 1], gap="large")

    # ── Cronómetro ────────────────────────────────────────────────────────
    with left:
        st.markdown("<div class='section-title'>Cronómetro</div>", unsafe_allow_html=True)

        if st.session_state.timer_running and st.session_state.timer_start:
            current_elapsed = st.session_state.timer_elapsed + (
                datetime.now() - st.session_state.timer_start).total_seconds()
        else:
            current_elapsed = st.session_state.timer_elapsed

        total_secs = int(current_elapsed)
        timer_str = f"{total_secs // 3600:02d}:{(total_secs % 3600) // 60:02d}:{total_secs % 60:02d}"
        st.markdown(f"<div class='timer-display'>{timer_str}</div>", unsafe_allow_html=True)

        timer_task = st.text_input("Task", value=st.session_state.timer_task,
                                   placeholder="Nome da task...",
                                   disabled=st.session_state.timer_running, key="tt_task_input")
        type_idx = (data["task_types"].index(st.session_state.timer_type)
                    if st.session_state.timer_type in data["task_types"] else 0)
        timer_type = st.selectbox("Tipo", data["task_types"], index=type_idx,
                                   disabled=st.session_state.timer_running, key="tt_type_input")
        timer_ticket = st.text_input("Ticket CSI ID", value=st.session_state.timer_ticket,
                                     placeholder="CSI-0001",
                                     disabled=st.session_state.timer_running, key="tt_ticket_input")

        if not st.session_state.timer_running:
            st.session_state.timer_task = timer_task
            st.session_state.timer_type = timer_type
            st.session_state.timer_ticket = timer_ticket

        btn1, btn2, btn3 = st.columns(3)
        with btn1:
            if not st.session_state.timer_running:
                if st.button("▶ Iniciar", use_container_width=True, type="primary"):
                    st.session_state.timer_running = True
                    st.session_state.timer_start = datetime.now()
                    st.rerun()
            else:
                if st.button("⏸ Parar", use_container_width=True):
                    st.session_state.timer_elapsed += (
                        datetime.now() - st.session_state.timer_start).total_seconds()
                    st.session_state.timer_running = False
                    st.session_state.timer_start = None
                    st.rerun()

        with btn2:
            if not st.session_state.timer_running and st.session_state.timer_elapsed > 0:
                if st.button("✓ Guardar", use_container_width=True, type="secondary"):
                    task = {
                        "id":      uid(),
                        "name":    st.session_state.timer_task or "Sem nome",
                        "type":    st.session_state.timer_type,
                        "ticket":  st.session_state.timer_ticket or "",
                        "minutes": max(1, round(st.session_state.timer_elapsed / 60)),
                        "addedAt": datetime.now().strftime("%H:%M"),
                    }
                    db_add_task(prof["id"], today, task)
                    st.session_state.timer_elapsed = 0
                    st.session_state.timer_task = ""
                    st.session_state.timer_type = None
                    st.session_state.timer_ticket = ""
                    st.rerun()

        with btn3:
            if not st.session_state.timer_running and st.session_state.timer_elapsed > 0:
                if st.button("↺ Reset", use_container_width=True):
                    st.session_state.timer_elapsed = 0
                    st.session_state.timer_running = False
                    st.session_state.timer_start = None
                    st.rerun()

        if st.session_state.timer_running:
            st.info("Cronómetro a correr... carrega em ⏸ Parar quando terminares.")
            st.rerun()

    # ── Registo Manual ────────────────────────────────────────────────────
    with right:
        st.markdown("<div class='section-title'>Registar Manualmente</div>", unsafe_allow_html=True)

        with st.form("manual_form", clear_on_submit=True):
            task_name = st.text_input("Nome da task", placeholder="Ex: Reunião sprint")
            task_type_manual = st.selectbox("Tipo", data["task_types"])
            ticket_id = st.text_input("Ticket CSI ID", placeholder="CSI-0001")
            tc1, tc2 = st.columns(2)
            with tc1:
                hours_in = st.number_input("Horas", min_value=0, max_value=23, value=0, step=1)
            with tc2:
                mins_in = st.number_input("Minutos", min_value=0, max_value=59, value=0, step=5)

            if st.form_submit_button("➕ Adicionar ao banco", use_container_width=True, type="primary"):
                total_mins = int(hours_in * 60 + mins_in)
                if task_name and total_mins > 0:
                    task = {
                        "id":      uid(),
                        "name":    task_name,
                        "type":    task_type_manual,
                        "ticket":  ticket_id,
                        "minutes": total_mins,
                        "addedAt": datetime.now().strftime("%H:%M"),
                    }
                    db_add_task(prof["id"], today, task)
                    st.success(f"Task '{task_name}' adicionada: {fmt_time(total_mins)}")
                    st.rerun()
                else:
                    st.warning("Preenche o nome e o tempo.")

    # ── Tasks do dia ──────────────────────────────────────────────────────
    st.divider()
    day_data = get_day(data, prof["id"], today)

    col_head, col_clear = st.columns([3, 1])
    with col_head:
        st.markdown("<div class='section-title'>Tasks de hoje</div>", unsafe_allow_html=True)
    with col_clear:
        if day_data["tasks"]:
            if st.button("🗑 Limpar dia", use_container_width=True):
                db_delete_day(prof["id"], today)
                st.rerun()

    if not day_data["tasks"]:
        st.info("Sem tasks registadas hoje. Usa o cronómetro ou o formulário acima.")
    else:
        # Formulário de edição
        if st.session_state.edit_task:
            ed = st.session_state.edit_task
            with st.form("edit_form"):
                st.markdown(f"### Editar Task: {ed['name']}")
                new_name   = st.text_input("Nome", value=ed["name"])
                type_list  = data["task_types"]
                type_idx   = type_list.index(ed.get("type", type_list[0])) if ed.get("type") in type_list else 0
                new_type   = st.selectbox("Tipo", type_list, index=type_idx)
                new_ticket = st.text_input("Ticket CSI", value=ed.get("ticket", ""))
                col_h, col_m = st.columns(2)
                with col_h:
                    new_hours = st.number_input("Horas",   value=ed["minutes"] // 60, min_value=0, max_value=23)
                with col_m:
                    new_mins  = st.number_input("Minutos", value=ed["minutes"] % 60,  min_value=0, max_value=59)

                btn_save, btn_cancel = st.columns(2)
                with btn_save:
                    if st.form_submit_button("💾 Guardar", type="primary", use_container_width=True):
                        db_update_task(ed["id"], new_name, new_type, new_ticket, new_hours * 60 + new_mins)
                        st.session_state.edit_task = None
                        st.rerun()
                with btn_cancel:
                    if st.form_submit_button("✖ Cancelar", use_container_width=True):
                        st.session_state.edit_task = None
                        st.rerun()
            st.divider()

        colors = ["#185FA5", "#639922", "#BA7517", "#A32D2D", "#533AB7", "#0F6E56"]
        header = st.columns([3, 1.5, 1.5, 1.5, 1, 1])
        for col, label in zip(header, ["**Task**", "**Tipo**", "**Ticket CSI**", "**Tempo**", "**Editar**", "**Apagar**"]):
            col.markdown(label)

        for i, task in enumerate(day_data["tasks"]):
            cols = st.columns([3, 1.5, 1.5, 1.5, 1, 1])
            dot = f"<span style='color:{colors[i % len(colors)]};font-size:18px'>●</span>"
            cols[0].markdown(f"{dot} {task['name']}", unsafe_allow_html=True)
            cols[1].markdown(f"<span class='badge'>{task.get('type', 'N/A')}</span>", unsafe_allow_html=True)
            cols[2].markdown(
                f"<span class='badge'>{task['ticket']}</span>" if task.get("ticket") else "—",
                unsafe_allow_html=True)
            cols[3].markdown(f"**{fmt_time(task['minutes'])}**")
            if cols[4].button("✏️", key=f"edit_{task['id']}"):
                st.session_state.edit_task = task.copy()
                st.rerun()
            if cols[5].button("✕", key=f"del_{task['id']}"):
                db_delete_task(task["id"])
                st.rerun()

        st.divider()
        total_today = sum(t["minutes"] for t in day_data["tasks"])
        st.markdown(f"**{len(day_data['tasks'])} tasks · Total: {fmt_time(total_today)}**")

# ════════════════════════════════════════════════════════════════════════════
# PAGE: HISTÓRICO
# ════════════════════════════════════════════════════════════════════════════

def render_historico():
    st.markdown("## 📅 Histórico & Calendário")

    days_with_tasks = get_days_with_tasks(data, prof["id"])

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button("◀ Mês anterior", use_container_width=True):
            st.session_state.view_month = (st.session_state.view_month - timedelta(days=1)).replace(day=1)
            st.rerun()
    with nav2:
        quick_date = st.date_input("Ir para data",
            value=datetime.fromisoformat(st.session_state.selected_date).date(),
            label_visibility="collapsed")
        if quick_date.isoformat() != st.session_state.selected_date:
            st.session_state.selected_date = quick_date.isoformat()
            st.session_state.view_month = quick_date.replace(day=1)
            st.rerun()
    with nav3:
        if st.button("Mês seguinte ▶", use_container_width=True):
            next_m = st.session_state.view_month.replace(day=28) + timedelta(days=4)
            st.session_state.view_month = next_m.replace(day=1)
            st.rerun()

    cal_col, tasks_col = st.columns([3, 2], gap="large")

    with cal_col:
        vm = st.session_state.view_month
        st.markdown(f"<div style='text-align:center;font-weight:600;font-size:15px;margin-bottom:.5rem'>"
                    f"{calendar.month_name[vm.month]} {vm.year}</div>", unsafe_allow_html=True)

        days_header = st.columns(7)
        for i, d in enumerate(["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]):
            days_header[i].markdown(
                f"<div style='text-align:center;font-size:11px;color:#888;font-weight:500'>{d}</div>",
                unsafe_allow_html=True)

        for week in calendar.monthcalendar(vm.year, vm.month):
            wcols = st.columns(7)
            for i, day in enumerate(week):
                if day == 0:
                    wcols[i].markdown("<div style='height:45px'></div>", unsafe_allow_html=True)
                else:
                    day_str = date(vm.year, vm.month, day).isoformat()
                    is_sel = day_str == st.session_state.selected_date
                    has = day_str in days_with_tasks
                    is_today = day_str == today_key()
                    lbl = f"{day} ●" if has and not is_sel else (f"**{day}**" if is_today and not is_sel else str(day))
                    if wcols[i].button(lbl, key=f"cal_{day_str}", use_container_width=True,
                                       type="primary" if is_sel else "secondary"):
                        st.session_state.selected_date = day_str
                        st.rerun()
        st.caption("💡 ● = dias com tasks")

    with tasks_col:
        sel_day = get_day(data, prof["id"], st.session_state.selected_date)
        sel_date_obj = datetime.fromisoformat(st.session_state.selected_date).date()
        date_label = "Hoje" if st.session_state.selected_date == today_key() else sel_date_obj.strftime("%d/%m/%Y")

        st.markdown(f"**Tasks de {date_label}**")

        if not sel_day["tasks"]:
            st.info("Sem tasks neste dia.")
        else:
            for task in sel_day["tasks"]:
                st.markdown(f"**{task['name']}**")
                meta = []
                if task.get("type"):   meta.append(f"📂 {task['type']}")
                if task.get("ticket"): meta.append(f"🎫 {task['ticket']}")
                if task.get("addedAt"): meta.append(f"🕐 {task['addedAt']}")
                meta.append(f"⏱ {fmt_time(task['minutes'])}")
                st.caption(" · ".join(meta))
                st.divider()

            total_sel = sum(t["minutes"] for t in sel_day["tasks"])
            st.markdown(f"**Total: {fmt_time(total_sel)}**")
            sel_remaining = int(prof["hours"] * 60) - total_sel
            if sel_remaining > 0:
                st.warning(f"⚠️ {fmt_time(sel_remaining)} não registadas")
            elif sel_remaining < 0:
                st.success(f"✓ +{fmt_time(abs(sel_remaining))} além da carga")
            else:
                st.success("✓ Carga completa registada")

# ════════════════════════════════════════════════════════════════════════════
# PAGE: CONFIGURAÇÕES
# ════════════════════════════════════════════════════════════════════════════

def render_configuracoes():
    st.markdown("## ⚙️ Configurações")

    tab1, tab2 = st.tabs(["Perfis", "Tipos de Task"])

    with tab1:
        st.markdown("### Perfis Existentes")
        for p in data["profiles"]:
            pc1, pc2, pc3 = st.columns([3, 1, 1])
            pc1.write(f"**{p['name']}**")
            pc2.write(f"{p['hours']}h/dia")
            if pc3.button("Remover", key=f"rmp_{p['id']}") and len(data["profiles"]) > 1:
                if p["id"] == data["active_profile"]:
                    other = next(x for x in data["profiles"] if x["id"] != p["id"])
                    db_set_active_profile(other["id"])
                db_delete_profile(p["id"])
                st.rerun()

        st.divider()
        st.markdown("### Adicionar Perfil")
        with st.form("add_profile_form", clear_on_submit=True):
            np1, np2 = st.columns(2)
            new_name  = np1.text_input("Nome")
            new_hours = np2.number_input("Horas diárias", min_value=1.0, max_value=24.0, value=8.0, step=0.5)
            if st.form_submit_button("Criar perfil", type="primary") and new_name:
                db_add_profile(new_name, float(new_hours))
                st.rerun()

    with tab2:
        st.markdown("### Tipos de Task Existentes")
        for task_type in data["task_types"]:
            tc1, tc2 = st.columns([4, 1])
            tc1.write(f"**{task_type}**")
            if tc2.button("Remover", key=f"rmt_{task_type}") and len(data["task_types"]) > 1:
                db_delete_task_type(task_type)
                st.rerun()

        st.divider()
        st.markdown("### Adicionar Tipo")
        with st.form("add_type_form", clear_on_submit=True):
            new_type = st.text_input("Nome do tipo")
            if st.form_submit_button("Adicionar tipo", type="primary"):
                if new_type and new_type not in data["task_types"]:
                    db_add_task_type(new_type)
                    st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# ROUTER
# ════════════════════════════════════════════════════════════════════════════

page = st.session_state.current_page
if page == "Dashboard":      render_dashboard()
elif page == "Registo":      render_registo()
elif page == "Histórico":    render_historico()
elif page == "Configurações": render_configuracoes()