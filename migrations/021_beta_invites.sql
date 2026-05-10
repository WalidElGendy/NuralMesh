-- Beta production invites and automatic child invites after user signup.
create extension if not exists pgcrypto;

create table if not exists invites (
    code text primary key,
    issued_to_user_id uuid references users(id) on delete set null,
    claimed_by_user_id uuid references users(id) on delete set null,
    claimed_by_provider_id uuid references providers(id) on delete set null,
    claimed_at timestamptz,
    revoked boolean not null default false,
    revoked_at timestamptz,
    notes text,
    created_at timestamptz not null default now()
);

create index if not exists idx_invites_issued_to_user_id on invites(issued_to_user_id);
create index if not exists idx_invites_claimed_by_user_id on invites(claimed_by_user_id);
create index if not exists idx_invites_claimed_by_provider_id on invites(claimed_by_provider_id);
create index if not exists idx_invites_created_at on invites(created_at);

create or replace function issue_beta_child_invites()
returns trigger as $$
declare
    created_count integer := 0;
    candidate_code text;
begin
    while created_count < 5 loop
        candidate_code := 'beta-' || encode(gen_random_bytes(6), 'hex');
        insert into invites (code, issued_to_user_id, notes)
        values (candidate_code, new.id, 'Auto-issued after beta signup')
        on conflict (code) do nothing;

        if found then
            created_count := created_count + 1;
        end if;
    end loop;

    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_issue_beta_child_invites on users;
create trigger trg_issue_beta_child_invites
after insert on users
for each row execute function issue_beta_child_invites();
