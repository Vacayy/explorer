"""Compose explicit candidate scenario dependencies; never falls back to SQLite."""
from pipeline.postgres_scenario_beneficiaries_fixture import resolve_beneficiaries


class PostgreSQLScenarioRuntime:
    def __init__(self,connect,*,inputs,run_llm,graph_writer):
        if not callable(getattr(inputs,'gather',None)) or not callable(run_llm) or not callable(graph_writer):
            raise ValueError('Explicit scenario inputs, model and graph writer are required')
        self.connect,self.inputs,self.model,self.graph_writer=connect,inputs,run_llm,graph_writer

    def gather(self,event,*,limit):return self.inputs.gather(event,limit=limit)
    def run_llm(self,prompt,**kwargs):return self.model(prompt,**kwargs)
    def resolve_beneficiaries(self,picks):return resolve_beneficiaries(self.connect,picks)
    def persist_causal(self,causal,*,conf_cap,source_status):
        return self.graph_writer(causal,conf_cap=conf_cap,source_status=source_status)
