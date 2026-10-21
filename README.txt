# ⏱ Registo de Tempo — Streamlit App

Aplicação de registo de tempo com cronómetro, banco de horas e perfis múltiplos.

## Instalação rápida

### 1. Instalar dependências
```bash
pip install streamlit
```

### 2. Correr a aplicação
```bash
streamlit run Contra.py
```

A app abre automaticamente no browser em http://localhost:8501

---

## Funcionalidades

- **Perfis múltiplos** — cada pessoa com a sua carga horária (ex: 7.5h ou 8h)
- **Cronómetro em tempo real** — inicia, para e guarda o tempo exato
- **Registo manual** — adiciona horas e minutos diretamente
- **Ticket CSI ID** — associa cada task a um ticket
- **Banco de horas** — mostra quanto tempo está registado vs disponível
- **Cálculo de desperdício** — horas não registadas = desperdício
- **Dados persistentes** — guardados em `time_tracker_data.json` na mesma pasta

---

## Estrutura de dados

Os dados são guardados automaticamente em `time_tracker_data.json`:
```json
{
  "profiles": [...],
  "active_profile": "p1",
  "days": {
    "p1": {
      "2025-04-29": {
        "tasks": [
          { "id": "...", "name": "Reunião sprint", "ticket": "CSI-0012", "minutes": 60, "addedAt": "09:30" }
        ]
      }
    }
  }
}
```

## Calendário
Como funciona:

Calendário mensal — vê todos os dias do mês num grid visual
Indicadores visuais — dias com ● têm tasks registadas
Navegação — botões para avançar/recuar meses ou saltar direto para uma data
Seleção de dia — clica em qualquer dia para ver as tasks desse dia
Painel de detalhes — mostra todas as tasks do dia selecionado com:

Nome, ticket CSI, hora de registo, duração
Total de horas registadas
Aviso se ficaram horas por registar ou se excedeste a carga