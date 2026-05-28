import streamlit as st
import json
import os
from datetime import date, datetime, timedelta
import calendar
import pandas as pd
from io import BytesIO
import uuid
import openpyxl

st.set_page_config(page_title="Registo de Tempo", page_icon="⏱", layout="wide")

DATA_FILE = "time_tracker_data.json"

# ════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "task_types" not in data:
                data["task_types"] = ["Reunião", "Desenvolvimento", "Suporte", "Documentação", "Email", "Revisão", "Planeamento", "Outro"]
            return data
    return {
        "profiles": [
            {"id": "p1", "name": "O meu perfil", "hours": 7.5}
        ],
        "active_profile": "p1",
        "days": {},
        "task_types": ["Reunião", "Desenvolvimento", "Suporte", "Documentação", "Email", "Revisão", "Planeamento", "Outro"]
    }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def uid():
    return str(uuid.uuid4())[:8]

def today_key():
    return date.today().isoformat()

def fmt_time(minutes):
    minutes = int(minutes)
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    h = minutes // 60
    m = minutes % 60
    return f"{sign}{h:02d}h{m:02d}m"

def get_day(data, profile_id, day_key):
    if profile_id not in data["days"]:
        data["days"][profile_id] = {}
    if day_key not in data["days"][profile_id]:
        data["days"][profile_id][day_key] = {"tasks": []}
    return data["days"][profile_id][day_key]

def total_logged(data, profile_id, day_key):
    day = get_day(data, profile_id, day_key)
    return sum(t["minutes"] for t in day["tasks"])

def get_days_with_tasks(data, profile_id):
    if profile_id not in data["days"]:
        return set()
    return {day_key for day_key, day_data in data["days"][profile_id].items() if day_data["tasks"]}

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
                "Adicionado às": task.get("addedAt", "")
            })
    
    if not rows:
        return None
    
    df = pd.DataFrame(rows)
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Tasks')
        worksheet = writer.sheets['Tasks']
        for idx, col in enumerate(df.columns):
            max_length = max(df[col].astype(str).apply(len).max(), len(col)) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = max_length
    
    return output.getvalue()

def get_stats_by_type(data, profile_id, start_date=None, end_date=None):
    if profile_id not in data["days"]:
        return {}
    
    stats = {}
    for day_key, day_data in data["days"][profile_id].items():
        if start_date and day_key < start_date:
            continue
        if end_date and day_key > end_date:
            continue
            
        for task in day_data["tasks"]:
            task_type = task.get("type", "Sem tipo")
            if task_type not in stats:
                stats[task_type] = {"count": 0, "minutes": 0}
            stats[task_type]["count"] += 1
            stats[task_type]["minutes"] += task["minutes"]
    
    return stats

def get_weekly_stats(data, profile_id, weeks=4):
    today = date.today()
    weeks_data = []
    
    for i in range(weeks):
        week_start = today - timedelta(days=today.weekday() + 7 * i)
        week_end = week_start + timedelta(days=6)
        
        total_mins = 0
        if profile_id in data["days"]:
            for day_key, day_data in data["days"][profile_id].items():
                day_date = datetime.fromisoformat(day_key).date()
                if week_start <= day_date <= week_end:
                    total_mins += sum(t["minutes"] for t in day_data["tasks"])
        
        weeks_data.append({
            "week": f"{week_start.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
            "minutes": total_mins
        })
    
    return list(reversed(weeks_data))

# ════════════════════════════════════════════════════════════════════════════
# SESSION STATE INITIALIZATION
# ════════════════════════════════════════════════════════════════════════════

if "timer_running" not in st.session_state:
    st.session_state.timer_running = False
if "timer_start" not in st.session_state:
    st.session_state.timer_start = None
if "timer_elapsed" not in st.session_state:
    st.session_state.timer_elapsed = 0
if "timer_task" not in st.session_state:
    st.session_state.timer_task = ""
if "timer_ticket" not in st.session_state:
    st.session_state.timer_ticket = ""
if "timer_type" not in st.session_state:
    st.session_state.timer_type = None
if "selected_date" not in st.session_state:
    st.session_state.selected_date = today_key()
if "view_month" not in st.session_state:
    st.session_state.view_month = date.today().replace(day=1)
if "current_page" not in st.session_state:
    st.session_state.current_page = "Registo"
if "edit_task" not in st.session_state:
    st.session_state.edit_task = None

# ════════════════════════════════════════════════════════════════════════════
# STYLES
# ════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.stat-box {
    background: #f8f9fa;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0;
}
.stat-label { font-size: 12px; color: #888; margin-bottom: 2px; }
.stat-value { font-size: 22px; font-weight: 600; }
.green { color: #3B6D11; }
.red { color: #A32D2D; }
.amber { color: #BA7517; }
.blue { color: #185FA5; }

.timer-display {
    font-size: 52px;
    font-weight: 600;
    text-align: center;
    font-variant-numeric: tabular-nums;
    letter-spacing: 3px;
    padding: 1rem 0 0.5rem;
    color: inherit;
}
.badge {
    display: inline-block;
    background: #E6F1FB;
    color: #0C447C;
    border-radius: 10px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 500;
}
.section-title {
    font-size: 11px;
    font-weight: 600;
    color: #999;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.75rem;
}
div[data-testid="stForm"] { border: none !important; padding: 0 !important; }
</style>
""", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ════════════════════════════════════════════════════════════════════════════

data = load_data()

# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR NAVIGATION
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
        data["active_profile"] = chosen_prof["id"]
        save_data(data)
        st.rerun()
    
    prof = chosen_prof
    
    st.divider()
    st.caption(f"📅 {today_key()}")

# ════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

def render_dashboard():
    st.markdown("## 📊 Dashboard")
    
    # Stats period selector
    period_col1, period_col2 = st.columns([2, 1])
    with period_col1:
        period = st.selectbox("Período", ["Últimos 7 dias", "Últimas 4 semanas", "Último mês", "Tudo"], index=1)
    with period_col2:
        excel_data = export_to_excel(data, prof["id"])
        if excel_data:
            st.download_button(
                "📥 Exportar Excel",
                data=excel_data,
                file_name=f"tasks_{prof['name']}_{today_key()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    
    st.divider()
    
    # Calculate date range
    end_date = today_key()
    if period == "Últimos 7 dias":
        start_date = (date.today() - timedelta(days=7)).isoformat()
    elif period == "Últimas 4 semanas":
        start_date = (date.today() - timedelta(days=28)).isoformat()
    elif period == "Último mês":
        start_date = date.today().replace(day=1).isoformat()
    else:
        start_date = None
    
    # Get stats
    type_stats = get_stats_by_type(data, prof["id"], start_date, end_date)
    
    if not type_stats:
        st.info("Sem dados para o período selecionado.")
        return
    
    # Summary metrics
    total_tasks = sum(s["count"] for s in type_stats.values())
    total_hours = sum(s["minutes"] for s in type_stats.values()) / 60
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Total de Tasks", total_tasks)
    c2.metric("Total de Horas", f"{total_hours:.1f}h")
    c3.metric("Média/Dia", f"{total_hours / 7:.1f}h" if period == "Últimos 7 dias" else f"{total_hours / 28:.1f}h")
    
    st.divider()
    
    # Charts
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("### Distribuição por Tipo")
        
        # Prepare data for chart
        chart_data = pd.DataFrame([
            {"Tipo": tipo, "Horas": stats["minutes"] / 60}
            for tipo, stats in sorted(type_stats.items(), key=lambda x: x[1]["minutes"], reverse=True)
        ])
        
        if not chart_data.empty:
            st.bar_chart(chart_data.set_index("Tipo"))
        
        # Table with details
        st.markdown("### Detalhes por Tipo")
        for tipo, stats in sorted(type_stats.items(), key=lambda x: x[1]["minutes"], reverse=True):
            st.markdown(f"**{tipo}**: {stats['count']} tasks · {fmt_time(stats['minutes'])}")
    
    with col_right:
        st.markdown("### Evolução Semanal")
        weekly = get_weekly_stats(data, prof["id"], 4)
        
        if weekly:
            weekly_df = pd.DataFrame([
                {"Semana": w["week"], "Horas": w["minutes"] / 60}
                for w in weekly
            ])
            st.line_chart(weekly_df.set_index("Semana"))
        
        # Efficiency metrics
        st.markdown("### Eficiência")
        
        days_with_data = len(get_days_with_tasks(data, prof["id"]))
        
        if start_date:
            start_dt = datetime.fromisoformat(start_date).date()
            period_days = (date.today() - start_dt).days + 1
        else:
            period_days = days_with_data
        
        if period_days > 0:
            coverage = (days_with_data / period_days * 100) if period != "Tudo" else 100
            st.metric("Dias registados", f"{days_with_data}/{period_days}", f"{coverage:.0f}%")
        
        avg_per_working_day = total_hours / days_with_data if days_with_data > 0 else 0
        st.metric("Média por dia de trabalho", f"{avg_per_working_day:.1f}h")
        
        target_hours = prof["hours"]
        efficiency = (avg_per_working_day / target_hours * 100) if target_hours > 0 else 0
        st.metric("Taxa de registo", f"{efficiency:.0f}%")

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
    
    # Stats
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>Carga diária</div>
            <div class='stat-value blue'>{prof['hours']}h</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>Registado</div>
            <div class='stat-value green'>{fmt_time(logged)}</div>
        </div>""", unsafe_allow_html=True)
        st.progress(pct / 100)
    with c3:
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>{'Banco restante' if remaining >= 0 else 'Excedido'}</div>
            <div class='stat-value amber'>{fmt_time(abs(remaining))}</div>
        </div>""", unsafe_allow_html=True)
    with c4:
        waste = remaining if remaining > 0 else 0
        st.markdown(f"""<div class='stat-box'>
            <div class='stat-label'>Desperdício</div>
            <div class='stat-value {'red' if waste > 0 else 'green'}'>{fmt_time(waste) if waste > 0 else '0h00m'}</div>
        </div>""", unsafe_allow_html=True)
    
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    
    # Main columns
    left, right = st.columns([1, 1], gap="large")
    
    # Cronómetro
    with left:
        st.markdown("<div class='section-title'>Cronómetro</div>", unsafe_allow_html=True)
        
        if st.session_state.timer_running and st.session_state.timer_start:
            current_elapsed = st.session_state.timer_elapsed + (datetime.now() - st.session_state.timer_start).total_seconds()
        else:
            current_elapsed = st.session_state.timer_elapsed
        
        total_secs = int(current_elapsed)
        h = total_secs // 3600
        m = (total_secs % 3600) // 60
        s = total_secs % 60
        timer_str = f"{h:02d}:{m:02d}:{s:02d}"
        
        st.markdown(f"<div class='timer-display'>{timer_str}</div>", unsafe_allow_html=True)
        
        timer_task = st.text_input("Task", value=st.session_state.timer_task,
                                    placeholder="Nome da task...",
                                    disabled=st.session_state.timer_running,
                                    key="tt_task_input")
        
        type_idx = data["task_types"].index(st.session_state.timer_type) if st.session_state.timer_type in data["task_types"] else 0
        timer_type = st.selectbox("Tipo", data["task_types"],
                                   index=type_idx,
                                   disabled=st.session_state.timer_running,
                                   key="tt_type_input")
        
        timer_ticket = st.text_input("Ticket CSI ID", value=st.session_state.timer_ticket,
                                      placeholder="CSI-0001",
                                      disabled=st.session_state.timer_running,
                                      key="tt_ticket_input")
        
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
                    elapsed_now = (datetime.now() - st.session_state.timer_start).total_seconds()
                    st.session_state.timer_elapsed += elapsed_now
                    st.session_state.timer_running = False
                    st.session_state.timer_start = None
                    st.rerun()
        
        with btn2:
            if not st.session_state.timer_running and st.session_state.timer_elapsed > 0:
                if st.button("✓ Guardar", use_container_width=True, type="secondary"):
                    mins = max(1, round(st.session_state.timer_elapsed / 60))
                    name = st.session_state.timer_task or "Sem nome"
                    task_type = st.session_state.timer_type
                    ticket = st.session_state.timer_ticket or ""
                    day_data = get_day(data, prof["id"], today)
                    day_data["tasks"].append({
                        "id": uid(), "name": name, "type": task_type, "ticket": ticket,
                        "minutes": mins,
                        "addedAt": datetime.now().strftime("%H:%M")
                    })
                    save_data(data)
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
    
    # Registo Manual
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
            submitted = st.form_submit_button("➕ Adicionar ao banco", use_container_width=True, type="primary")
            if submitted:
                total_mins = int(hours_in * 60 + mins_in)
                if task_name and total_mins > 0:
                    day_data = get_day(data, prof["id"], today)
                    day_data["tasks"].append({
                        "id": uid(), "name": task_name, "type": task_type_manual, "ticket": ticket_id,
                        "minutes": total_mins,
                        "addedAt": datetime.now().strftime("%H:%M")
                    })
                    save_data(data)
                    st.success(f"Task '{task_name}' adicionada: {fmt_time(total_mins)}")
                    st.rerun()
                else:
                    st.warning("Preenche o nome e o tempo.")
    
    # Tasks do dia
    st.divider()
    day_data = get_day(data, prof["id"], today)
    
    col_head, col_clear = st.columns([3, 1])
    with col_head:
        st.markdown("<div class='section-title'>Tasks de hoje</div>", unsafe_allow_html=True)
    with col_clear:
        if day_data["tasks"]:
            if st.button("🗑 Limpar dia", use_container_width=True):
                data["days"][prof["id"]][today] = {"tasks": []}
                save_data(data)
                st.rerun()
    
    if not day_data["tasks"]:
        st.info("Sem tasks registadas hoje. Usa o cronómetro ou o formulário acima.")
    else:
        # Edit modal
        if st.session_state.edit_task:
            edit_data = st.session_state.edit_task
            with st.form("edit_form"):
                st.markdown(f"### Editar Task: {edit_data['name']}")
                new_name = st.text_input("Nome", value=edit_data["name"])
                new_type = st.selectbox("Tipo", data["task_types"], index=data["task_types"].index(edit_data.get("type", data["task_types"][0])))
                new_ticket = st.text_input("Ticket CSI", value=edit_data.get("ticket", ""))
                col_h, col_m = st.columns(2)
                with col_h:
                    new_hours = st.number_input("Horas", value=edit_data["minutes"]//60, min_value=0, max_value=23)
                with col_m:
                    new_mins = st.number_input("Minutos", value=edit_data["minutes"]%60, min_value=0, max_value=59)
                
                btn_save, btn_cancel = st.columns(2)
                with btn_save:
                    if st.form_submit_button("💾 Guardar", type="primary", use_container_width=True):
                        # Update task
                        for task in day_data["tasks"]:
                            if task["id"] == edit_data["id"]:
                                task["name"] = new_name
                                task["type"] = new_type
                                task["ticket"] = new_ticket
                                task["minutes"] = new_hours * 60 + new_mins
                                break
                        save_data(data)
                        st.session_state.edit_task = None
                        st.rerun()
                with btn_cancel:
                    if st.form_submit_button("✖ Cancelar", use_container_width=True):
                        st.session_state.edit_task = None
                        st.rerun()
            st.divider()
        
        colors = ["#185FA5", "#639922", "#BA7517", "#A32D2D", "#533AB7", "#0F6E56"]
        header = st.columns([3, 1.5, 1.5, 1.5, 1, 1])
        header[0].markdown("**Task**")
        header[1].markdown("**Tipo**")
        header[2].markdown("**Ticket CSI**")
        header[3].markdown("**Tempo**")
        header[4].markdown("**Editar**")
        header[5].markdown("**Apagar**")
        
        for i, task in enumerate(day_data["tasks"]):
            cols = st.columns([3, 1.5, 1.5, 1.5, 1, 1])
            dot = f"<span style='color:{colors[i % len(colors)]};font-size:18px'>●</span>"
            cols[0].markdown(f"{dot} {task['name']}", unsafe_allow_html=True)
            cols[1].markdown(f"<span class='badge'>{task.get('type', 'N/A')}</span>", unsafe_allow_html=True)
            cols[2].markdown(
                f"<span class='badge'>{task['ticket']}</span>" if task.get("ticket") else "—",
                unsafe_allow_html=True
            )
            cols[3].markdown(f"**{fmt_time(task['minutes'])}**")
            if cols[4].button("✏️", key=f"edit_{task['id']}"):
                st.session_state.edit_task = task.copy()
                st.rerun()
            if cols[5].button("✕", key=f"del_{task['id']}"):
                day_data["tasks"] = [t for t in day_data["tasks"] if t["id"] != task["id"]]
                save_data(data)
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
    
    # Month navigation
    nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
    with nav_col1:
        if st.button("◀ Mês anterior", use_container_width=True):
            current_month = st.session_state.view_month
            st.session_state.view_month = (current_month - timedelta(days=1)).replace(day=1)
            st.rerun()
    
    with nav_col2:
        quick_date = st.date_input(
            "Ir para data",
            value=datetime.fromisoformat(st.session_state.selected_date).date(),
            label_visibility="collapsed"
        )
        if quick_date.isoformat() != st.session_state.selected_date:
            st.session_state.selected_date = quick_date.isoformat()
            st.session_state.view_month = quick_date.replace(day=1)
            st.rerun()
    
    with nav_col3:
        if st.button("Mês seguinte ▶", use_container_width=True):
            current_month = st.session_state.view_month
            next_month = current_month.replace(day=28) + timedelta(days=4)
            st.session_state.view_month = next_month.replace(day=1)
            st.rerun()
    
    # Display calendar
    cal_col, tasks_col = st.columns([3, 2], gap="large")
    
    with cal_col:
        st.markdown(f"<div style='text-align:center; font-weight:600; font-size:15px; margin-bottom:0.5rem;'>{calendar.month_name[st.session_state.view_month.month]} {st.session_state.view_month.year}</div>", unsafe_allow_html=True)
        
        days_header = st.columns(7)
        for i, day in enumerate(['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']):
            days_header[i].markdown(f"<div style='text-align:center; font-size:11px; color:#888; font-weight:500;'>{day}</div>", unsafe_allow_html=True)
        
        cal = calendar.monthcalendar(st.session_state.view_month.year, st.session_state.view_month.month)
        
        for week in cal:
            week_cols = st.columns(7)
            for i, day in enumerate(week):
                if day == 0:
                    week_cols[i].markdown("<div style='height:45px;'></div>", unsafe_allow_html=True)
                else:
                    day_date = date(st.session_state.view_month.year, st.session_state.view_month.month, day)
                    day_str = day_date.isoformat()
                    
                    is_today = day_str == today_key()
                    is_selected = day_str == st.session_state.selected_date
                    has_tasks = day_str in days_with_tasks
                    
                    button_type = "primary" if is_selected else "secondary"
                    
                    label = f"{day}"
                    if has_tasks and not is_selected:
                        label = f"{day} ●"
                    if is_today and not is_selected:
                        label = f"**{day}**"
                    
                    if week_cols[i].button(
                        label,
                        key=f"cal_{day_str}",
                        use_container_width=True,
                        type=button_type if is_selected else "secondary",
                        disabled=False
                    ):
                        st.session_state.selected_date = day_str
                        st.rerun()
        
        st.caption("💡 ● = dias com tasks")
    
    with tasks_col:
        selected_day_data = get_day(data, prof["id"], st.session_state.selected_date)
        selected_date_obj = datetime.fromisoformat(st.session_state.selected_date).date()
        
        is_today = st.session_state.selected_date == today_key()
        date_label = "Hoje" if is_today else selected_date_obj.strftime("%d/%m/%Y")
        
        st.markdown(f"**Tasks de {date_label}**")
        
        if not selected_day_data["tasks"]:
            st.info("Sem tasks neste dia.")
        else:
            total_selected = sum(t["minutes"] for t in selected_day_data["tasks"])
            
            for task in selected_day_data["tasks"]:
                with st.container():
                    st.markdown(f"**{task['name']}**")
                    meta_parts = []
                    if task.get('type'):
                        meta_parts.append(f"📂 {task['type']}")
                    if task.get('ticket'):
                        meta_parts.append(f"🎫 {task['ticket']}")
                    if task.get('addedAt'):
                        meta_parts.append(f"🕐 {task['addedAt']}")
                    meta_parts.append(f"⏱ {fmt_time(task['minutes'])}")
                    st.caption(" · ".join(meta_parts))
                    st.divider()
            
            st.markdown(f"**Total: {fmt_time(total_selected)}**")
            
            selected_bank = int(prof["hours"] * 60)
            selected_remaining = selected_bank - total_selected
            
            if selected_remaining > 0:
                st.warning(f"⚠️ {fmt_time(selected_remaining)} não registadas")
            elif selected_remaining < 0:
                st.success(f"✓ +{fmt_time(abs(selected_remaining))} além da carga")
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
                data["profiles"] = [x for x in data["profiles"] if x["id"] != p["id"]]
                if data["active_profile"] == p["id"]:
                    data["active_profile"] = data["profiles"][0]["id"]
                save_data(data)
                st.rerun()
        
        st.divider()
        st.markdown("### Adicionar Perfil")
        with st.form("add_profile_form", clear_on_submit=True):
            np1, np2 = st.columns(2)
            new_name = np1.text_input("Nome")
            new_hours = np2.number_input("Horas diárias", min_value=1.0, max_value=24.0, value=8.0, step=0.5)
            if st.form_submit_button("Criar perfil", type="primary"):
                if new_name:
                    data["profiles"].append({"id": uid(), "name": new_name, "hours": float(new_hours)})
                    save_data(data)
                    st.rerun()
    
    with tab2:
        st.markdown("### Tipos de Task Existentes")
        for i, task_type in enumerate(data["task_types"]):
            tc1, tc2 = st.columns([4, 1])
            tc1.write(f"**{task_type}**")
            if tc2.button("Remover", key=f"rmt_{i}") and len(data["task_types"]) > 1:
                data["task_types"].remove(task_type)
                save_data(data)
                st.rerun()
        
        st.divider()
        st.markdown("### Adicionar Tipo")
        with st.form("add_type_form", clear_on_submit=True):
            new_type = st.text_input("Nome do tipo")
            if st.form_submit_button("Adicionar tipo", type="primary"):
                if new_type and new_type not in data["task_types"]:
                    data["task_types"].append(new_type)
                    save_data(data)
                    st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# RENDER CURRENT PAGE
# ════════════════════════════════════════════════════════════════════════════

if st.session_state.current_page == "Dashboard":
    render_dashboard()
elif st.session_state.current_page == "Registo":
    render_registo()
elif st.session_state.current_page == "Histórico":
    render_historico()
elif st.session_state.current_page == "Configurações":
    render_configuracoes()