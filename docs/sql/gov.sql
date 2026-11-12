-- 🏛️ 경영실 (2026-11-12) — Supabase(BUZA_ALARM) SQL Editor 에서 한 번. 다시 실행해도 안전(if not exists / or replace).
-- 모든 변경은 트리거가 gov_audit 에 전/후 그대로 남긴다(append-only). RLS on + 정책 없음 = service_role 전용.
create table if not exists gov_items (
  id bigserial primary key,
  kind text not null check (kind in ('kpi','roadmap','decision','issue','meeting')),
  title text not null,
  body text default '',
  status text default '',
  dept text default '',
  owner text default '',
  period text default '',
  due date,
  progress int,
  meta jsonb not null default '{}'::jsonb,
  deleted boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  updated_by text not null default 'system'
);
create index if not exists gov_items_kind on gov_items(kind, deleted);

create table if not exists gov_kpi_weekly (
  week date not null,
  key text not null,
  value double precision,
  note text default '',
  source text not null default 'manual',
  updated_at timestamptz not null default now(),
  updated_by text not null default 'system',
  primary key (week, key)
);

create table if not exists gov_audit (
  id bigserial primary key,
  at timestamptz not null default now(),
  tbl text not null,
  row_key text not null,
  action text not null,
  actor text,
  before jsonb,
  after jsonb
);
create index if not exists gov_audit_at on gov_audit(at desc);

create table if not exists usage_events (
  id bigserial primary key,
  at timestamptz not null default now(),
  uid text not null,
  event text not null,
  tab text default ''
);
create index if not exists usage_events_at on usage_events(at desc);

-- 기록은 AFTER 트리거 — upsert(INSERT … ON CONFLICT DO UPDATE)에서 BEFORE INSERT 는 충돌 전에 불려 가짜 '추가'가 남는다.
create or replace function gov_touch_fn() returns trigger language plpgsql as $$
begin NEW.updated_at := now(); return NEW; end $$;

create or replace function gov_audit_fn() returns trigger language plpgsql security definer set search_path = public as $$
declare k text;
begin
  if TG_TABLE_NAME = 'gov_kpi_weekly' then
    k := coalesce(NEW.week, OLD.week)::text || '/' || coalesce(NEW.key, OLD.key);
  else
    k := coalesce(NEW.id, OLD.id)::text;
  end if;
  if TG_OP = 'UPDATE' and to_jsonb(NEW) - 'updated_at' - 'updated_by' = to_jsonb(OLD) - 'updated_at' - 'updated_by' then
    return null;                                   -- 내용이 같으면 이력 안 남김
  end if;
  insert into gov_audit(tbl,row_key,action,actor,before,after)
  values (TG_TABLE_NAME, k, TG_OP,
          case when TG_OP='DELETE' then OLD.updated_by else NEW.updated_by end,
          case when TG_OP='INSERT' then null else to_jsonb(OLD) end,
          case when TG_OP='DELETE' then null else to_jsonb(NEW) end);
  return null;
end $$;

drop trigger if exists gov_items_audit on gov_items;
drop trigger if exists gov_items_touch on gov_items;
create trigger gov_items_touch before update on gov_items for each row execute function gov_touch_fn();
create trigger gov_items_audit after insert or update or delete on gov_items for each row execute function gov_audit_fn();
drop trigger if exists gov_kpi_audit on gov_kpi_weekly;
drop trigger if exists gov_kpi_touch on gov_kpi_weekly;
create trigger gov_kpi_touch before update on gov_kpi_weekly for each row execute function gov_touch_fn();
create trigger gov_kpi_audit after insert or update or delete on gov_kpi_weekly for each row execute function gov_audit_fn();

create or replace function gov_audit_lock() returns trigger language plpgsql as $$
begin raise exception 'gov_audit is append-only'; end $$;
drop trigger if exists gov_audit_ro on gov_audit;
create trigger gov_audit_ro before update or delete on gov_audit for each row execute function gov_audit_lock();

alter table gov_items enable row level security;
alter table gov_kpi_weekly enable row level security;
alter table gov_audit enable row level security;
alter table usage_events enable row level security;
