-- Initial setup for a fresh Supabase project.
-- Run once in that project's SQL Editor.
-- Existing installations need separate upgrade migrations.

begin;

create table public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text,
    approval_status text not null default 'pending'
        check (approval_status in ('pending', 'approved', 'declined'))
);

alter table public.profiles enable row level security;

revoke all on public.profiles from anon, authenticated;
grant select on public.profiles to authenticated;

create policy "Users can read their own profile"
on public.profiles
for select
to authenticated
using ((select auth.uid()) = id);

create function public.wpl_create_profile()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    insert into public.profiles (id, email)
    values (new.id, new.email);
    return new;
end;
$$;

revoke all on function public.wpl_create_profile()
from public, anon, authenticated;

create trigger wpl_auth_user_created
after insert on auth.users
for each row execute function public.wpl_create_profile();

-- Populate profiles for any accounts created before this setup.
insert into public.profiles (id, email)
select id, email from auth.users
on conflict (id) do nothing;

commit;
