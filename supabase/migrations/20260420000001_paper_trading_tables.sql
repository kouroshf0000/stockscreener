create table if not exists paper_trades (
    id bigserial primary key,
    created_at timestamptz default now(),
    ticker text not null,
    side text not null,
    notional_usd numeric not null,
    order_id text,
    status text,
    strategy text,
    conviction_score numeric,
    upside_pct numeric,
    signal_direction text,
    signal_confidence text,
    entry_rationale text,
    stop_loss_pct numeric,
    target_pct numeric,
    stop_price numeric,
    target_price numeric
);

create table if not exists conviction_screen_runs (
    id bigserial primary key,
    created_at timestamptz default now(),
    run_at timestamptz default now(),
    candidates jsonb not null default '[]'::jsonb,
    strategy text,
    top_n int
);

create table if not exists thirteenf_digest_cache (
    id bigserial primary key,
    created_at timestamptz default now(),
    latest_label text not null unique,
    payload jsonb not null
);
