--
-- PostgreSQL database dump
--


-- Dumped from database version 17.11 (Debian 17.11-1.pgdg12+2)
-- Dumped by pg_dump version 17.11 (Debian 17.11-1.pgdg12+2)

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
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: business_processes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.business_processes (
    id text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: department_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.department_settings (
    key text NOT NULL,
    value jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: knowledge_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_categories (
    id text NOT NULL,
    parent_id text,
    name text NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: knowledge_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_chunks (
    id text NOT NULL,
    document_id text NOT NULL,
    parent_chunk_id text,
    chunk_index integer NOT NULL,
    section_path text DEFAULT ''::text NOT NULL,
    content text NOT NULL,
    token_count integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    embedding public.vector(1024),
    embedding_model text DEFAULT ''::text NOT NULL
);


--
-- Name: knowledge_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_documents (
    id text NOT NULL,
    title text NOT NULL,
    category_id text,
    original_name text NOT NULL,
    original_path text NOT NULL,
    mime_type text NOT NULL,
    status text NOT NULL,
    is_generation_template boolean DEFAULT false NOT NULL,
    template_family text DEFAULT ''::text NOT NULL,
    template_variant text DEFAULT ''::text NOT NULL,
    version text DEFAULT ''::text NOT NULL,
    applicable_process_id text DEFAULT ''::text NOT NULL,
    applicable_step_id text DEFAULT ''::text NOT NULL,
    applicable_scenario text DEFAULT ''::text NOT NULL,
    summary text DEFAULT ''::text NOT NULL,
    parsed_text text NOT NULL,
    chunk_settings jsonb NOT NULL,
    document_embedding public.vector(1024),
    embedding_model text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    is_reference_knowledge boolean DEFAULT true NOT NULL,
    document_type text DEFAULT ''::text NOT NULL,
    keywords jsonb DEFAULT '[]'::jsonb NOT NULL,
    outline jsonb DEFAULT '[]'::jsonb NOT NULL,
    purpose_id text NOT NULL,
    CONSTRAINT knowledge_documents_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'effective'::text, 'obsolete'::text])))
);


--
-- Name: knowledge_purposes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_purposes (
    id text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    can_generate_template boolean NOT NULL,
    chunk_body boolean NOT NULL,
    inherit_chunking boolean DEFAULT true NOT NULL,
    chunk_settings jsonb NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT knowledge_purposes_check CHECK ((can_generate_template OR chunk_body))
);


--
-- Name: process_steps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.process_steps (
    process_id text NOT NULL,
    id text NOT NULL,
    name text NOT NULL,
    objective text NOT NULL,
    required_inputs jsonb DEFAULT '[]'::jsonb NOT NULL,
    required_outputs jsonb DEFAULT '[]'::jsonb NOT NULL,
    completion_criteria jsonb DEFAULT '[]'::jsonb NOT NULL,
    knowledge_scopes jsonb DEFAULT '[]'::jsonb NOT NULL,
    instructions text DEFAULT ''::text NOT NULL,
    sort_order integer NOT NULL
);


--
-- Name: business_processes business_processes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.business_processes
    ADD CONSTRAINT business_processes_pkey PRIMARY KEY (id);


--
-- Name: department_settings department_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.department_settings
    ADD CONSTRAINT department_settings_pkey PRIMARY KEY (key);


--
-- Name: knowledge_categories knowledge_categories_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_categories
    ADD CONSTRAINT knowledge_categories_pkey PRIMARY KEY (id);


--
-- Name: knowledge_chunks knowledge_chunks_document_id_chunk_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_document_id_chunk_index_key UNIQUE (document_id, chunk_index);


--
-- Name: knowledge_chunks knowledge_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_pkey PRIMARY KEY (id);


--
-- Name: knowledge_documents knowledge_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT knowledge_documents_pkey PRIMARY KEY (id);


--
-- Name: knowledge_purposes knowledge_purposes_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_purposes
    ADD CONSTRAINT knowledge_purposes_name_key UNIQUE (name);


--
-- Name: knowledge_purposes knowledge_purposes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_purposes
    ADD CONSTRAINT knowledge_purposes_pkey PRIMARY KEY (id);


--
-- Name: process_steps process_steps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.process_steps
    ADD CONSTRAINT process_steps_pkey PRIMARY KEY (process_id, id);


--
-- Name: knowledge_categories_sibling_name; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX knowledge_categories_sibling_name ON public.knowledge_categories USING btree (COALESCE(parent_id, ''::text), name);


--
-- Name: knowledge_chunks_document_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX knowledge_chunks_document_id ON public.knowledge_chunks USING btree (document_id);


--
-- Name: knowledge_categories knowledge_categories_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_categories
    ADD CONSTRAINT knowledge_categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.knowledge_categories(id) ON DELETE RESTRICT;


--
-- Name: knowledge_chunks knowledge_chunks_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.knowledge_documents(id) ON DELETE CASCADE;


--
-- Name: knowledge_documents knowledge_documents_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT knowledge_documents_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.knowledge_categories(id) ON DELETE RESTRICT;


--
-- Name: knowledge_documents knowledge_documents_purpose_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_documents
    ADD CONSTRAINT knowledge_documents_purpose_id_fkey FOREIGN KEY (purpose_id) REFERENCES public.knowledge_purposes(id) ON DELETE RESTRICT;


--
-- Name: process_steps process_steps_process_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.process_steps
    ADD CONSTRAINT process_steps_process_id_fkey FOREIGN KEY (process_id) REFERENCES public.business_processes(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

