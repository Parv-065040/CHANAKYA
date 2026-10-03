-- CHANAKYA schema for Supabase (PostgreSQL + pgvector). Run once in the Supabase SQL editor.
-- The app uses the SERVICE ROLE key from the backend only; never expose that key to a browser.
create extension if not exists vector;

create table if not exists documents (
  document_id text primary key,
  name text not null,
  department text not null,
  version int not null default 1,
  status text not null,                 -- indexed | superseded | failed
  size_bytes bigint,
  n_chunks int, n_tables int, pages int,
  sha256 text,
  uploaded_at double precision,
  error text default ''
);

create table if not exists chunks (
  chunk_id text primary key,
  document_id text not null references documents(document_id) on delete cascade,
  document_name text, department text not null,
  page_start int, page_end int, section text,
  content_type text check (content_type in ('text','table')),
  table_id text, table_rows int default 0,
  text text not null,
  embedding vector(1024),               -- must equal EMBEDDING_DIMENSION
  fts tsvector generated always as (to_tsvector('simple', text)) stored
);
create index if not exists chunks_dept_idx on chunks (department);
create index if not exists chunks_fts_idx on chunks using gin (fts);
create index if not exists chunks_emb_idx on chunks using hnsw (embedding vector_cosine_ops);

create table if not exists app_meta (key text primary key, value text);

-- Private storage bucket for raw uploads (create in Dashboard > Storage, name = SUPABASE_BUCKET, private).

alter table documents enable row level security;
alter table chunks enable row level security;
alter table app_meta enable row level security;
-- No policies are defined: only the service-role key (server side) can read/write.
