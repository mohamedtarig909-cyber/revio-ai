-- Supabase Row Level Security policies for Revio AI
-- Apply after running Alembic migrations

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaigns ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_health ENABLE ROW LEVEL SECURITY;

-- Users can only read their own record
CREATE POLICY users_select_own ON users
    FOR SELECT USING (auth.uid()::text = id::text);

-- Organization-scoped access via JWT claim organization_id
CREATE POLICY org_select_own ON organizations
    FOR SELECT USING (id::text = current_setting('request.jwt.claims', true)::json->>'organization_id');

CREATE POLICY leads_org_isolation ON leads
    FOR ALL USING (organization_id::text = current_setting('request.jwt.claims', true)::json->>'organization_id');

CREATE POLICY lead_analysis_org_isolation ON lead_analysis
    FOR ALL USING (
        lead_id IN (
            SELECT id FROM leads
            WHERE organization_id::text = current_setting('request.jwt.claims', true)::json->>'organization_id'
        )
    );

CREATE POLICY campaigns_org_isolation ON campaigns
    FOR ALL USING (organization_id::text = current_setting('request.jwt.claims', true)::json->>'organization_id');

CREATE POLICY agent_runs_org_isolation ON agent_runs
    FOR ALL USING (organization_id::text = current_setting('request.jwt.claims', true)::json->>'organization_id');

CREATE POLICY daily_reports_org_isolation ON daily_reports
    FOR ALL USING (organization_id::text = current_setting('request.jwt.claims', true)::json->>'organization_id');

CREATE POLICY pipeline_health_org_isolation ON pipeline_health
    FOR ALL USING (organization_id::text = current_setting('request.jwt.claims', true)::json->>'organization_id');

CREATE POLICY crm_integrations_org_isolation ON crm_integrations
    FOR ALL USING (organization_id::text = current_setting('request.jwt.claims', true)::json->>'organization_id');

-- Service role bypasses RLS for backend workers
-- Backend uses service role key, not anon key
