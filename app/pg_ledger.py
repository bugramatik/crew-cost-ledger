import streamlit as st
import pandas as pd

import cost_ledger
from i18n import t


class PageLedger:
    def __init__(self):
        self.name = t('page.ledger')

    def draw_totals(self, records):
        total_tokens = sum(int(record.get('total_tokens') or 0) for record in records)
        total_cost = sum(float(record.get('total_cost_usd') or 0.0) for record in records)
        col1, col2, col3 = st.columns(3)
        col1.metric(t('ledger.runs'), len(records))
        col2.metric(t('ledger.tokens'), f'{total_tokens:,}')
        col3.metric(t('ledger.spend'), f'${total_cost:,.2f}')

    def draw_by_crew(self, records):
        rows = cost_ledger.aggregate_by_crew(records)
        if not rows:
            return
        st.subheader(t('ledger.by_crew'))
        frame = pd.DataFrame(rows).rename(columns={
            'crew_name': t('ledger.crew'),
            'runs': t('ledger.runs'),
            'tokens': t('ledger.tokens'),
            'cost_usd': t('ledger.spend'),
        })
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.bar_chart(frame.set_index(t('ledger.crew'))[t('ledger.spend')])

    def draw_by_day(self, records):
        rows = cost_ledger.aggregate_by_day(records)
        if not rows:
            return
        st.subheader(t('ledger.by_day'))
        frame = pd.DataFrame(rows).rename(columns={
            'day': t('ledger.day'),
            'runs': t('ledger.runs'),
            'tokens': t('ledger.tokens'),
            'cost_usd': t('ledger.spend'),
        })
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.bar_chart(frame.set_index(t('ledger.day'))[t('ledger.spend')])

    def draw_recent(self, records):
        st.subheader(t('ledger.recent'))
        rows = []
        for record in records[:50]:
            for entry in record.get('entries', []):
                rows.append({
                    t('ledger.day'): (record.get('created_at') or '')[:10],
                    t('ledger.crew'): record.get('crew_name'),
                    t('ledger.agent'): entry.get('agent'),
                    t('ledger.task'): entry.get('task'),
                    t('ledger.model'): entry.get('model'),
                    t('ledger.tokens'): entry.get('total_tokens'),
                    t('ledger.spend'): entry.get('cost_usd'),
                })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.write(t('ledger.no_records'))

    def draw(self):
        st.subheader(self.name)
        records = cost_ledger.load_cost_records()
        if not records:
            st.write(t('ledger.no_records'))
            return
        self.draw_totals(records)
        self.draw_by_crew(records)
        self.draw_by_day(records)
        self.draw_recent(records)
