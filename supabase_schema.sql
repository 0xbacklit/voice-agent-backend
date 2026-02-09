create table if not exists appointments (
  id text primary key,
  contact_number text not null,
  name text not null,
  date text not null,
  time text not null,
  status text not null default 'booked',
  created_at timestamptz default now()
);

create unique index if not exists appointments_unique_slot
  on appointments(date, time)
  where status = 'booked';

create table if not exists summaries (
  session_id text primary key,
  summary text not null,
  booked_appointments jsonb not null,
  preferences jsonb not null,
  created_at timestamptz default now()
);
