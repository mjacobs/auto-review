-- db/reference/agent_review.sql — READ-ONLY SNAPSHOT of the live agent_review
-- schema, taken 2026-06-11 via `pg_dump --schema-only -n agent_review` against
-- the shared instance (<pg-host>).
--
-- This is NOT a migration. migrate.sh only applies db/migrations/[0-9]*.sql;
-- this file documents the precedent the db/ foundation follows: schema-per-
-- domain in the same database, schema owned by the admin role, a narrow
-- per-service role (agent_review) granted DML explicitly. The schema itself
-- is owned by agent-review/migrations/001_init.sql and matches it (tables,
-- indexes, and the FK to agentsview.sessions all present live).
--
-- Scrubbed for the public repo: pg_dump's \restrict/\unrestrict lines removed;
-- no host details appear below.

--
-- PostgreSQL database dump
--


-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.3

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: agent_review; Type: SCHEMA; Schema: -; Owner: admin
--

CREATE SCHEMA agent_review;


ALTER SCHEMA agent_review OWNER TO admin;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: daily_reports; Type: TABLE; Schema: agent_review; Owner: admin
--

CREATE TABLE agent_review.daily_reports (
    report_date date NOT NULL,
    generated_at timestamp with time zone DEFAULT now() NOT NULL,
    model text NOT NULL,
    sessions_included text[] NOT NULL,
    narrative_md text NOT NULL,
    stats jsonb NOT NULL,
    prompt_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    cached_tokens integer DEFAULT 0 NOT NULL,
    est_cost_usd numeric(10,4) NOT NULL
);


ALTER TABLE agent_review.daily_reports OWNER TO admin;

--
-- Name: session_digests; Type: TABLE; Schema: agent_review; Owner: admin
--

CREATE TABLE agent_review.session_digests (
    session_id text NOT NULL,
    data_version integer NOT NULL,
    model text NOT NULL,
    prompt_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    cached_tokens integer DEFAULT 0 NOT NULL,
    digest jsonb NOT NULL,
    generated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE agent_review.session_digests OWNER TO admin;

--
-- Name: daily_reports daily_reports_pkey; Type: CONSTRAINT; Schema: agent_review; Owner: admin
--

ALTER TABLE ONLY agent_review.daily_reports
    ADD CONSTRAINT daily_reports_pkey PRIMARY KEY (report_date);


--
-- Name: session_digests session_digests_pkey; Type: CONSTRAINT; Schema: agent_review; Owner: admin
--

ALTER TABLE ONLY agent_review.session_digests
    ADD CONSTRAINT session_digests_pkey PRIMARY KEY (session_id);


--
-- Name: idx_daily_reports_generated_at; Type: INDEX; Schema: agent_review; Owner: admin
--

CREATE INDEX idx_daily_reports_generated_at ON agent_review.daily_reports USING btree (generated_at);


--
-- Name: idx_session_digests_generated_at; Type: INDEX; Schema: agent_review; Owner: admin
--

CREATE INDEX idx_session_digests_generated_at ON agent_review.session_digests USING btree (generated_at);


--
-- Name: session_digests session_digests_session_id_fkey; Type: FK CONSTRAINT; Schema: agent_review; Owner: admin
--

ALTER TABLE ONLY agent_review.session_digests
    ADD CONSTRAINT session_digests_session_id_fkey FOREIGN KEY (session_id) REFERENCES agentsview.sessions(id) ON DELETE CASCADE;


--
-- Name: SCHEMA agent_review; Type: ACL; Schema: -; Owner: admin
--

GRANT USAGE ON SCHEMA agent_review TO agent_review;


--
-- Name: TABLE daily_reports; Type: ACL; Schema: agent_review; Owner: admin
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE agent_review.daily_reports TO agent_review;


--
-- Name: TABLE session_digests; Type: ACL; Schema: agent_review; Owner: admin
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE agent_review.session_digests TO agent_review;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: agent_review; Owner: admin
--

ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA agent_review GRANT SELECT,USAGE ON SEQUENCES TO agent_review;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: agent_review; Owner: admin
--

ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA agent_review GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO agent_review;


--
-- PostgreSQL database dump complete
--


