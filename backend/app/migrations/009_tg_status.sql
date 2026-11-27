-- Phase 3.1: the Telegram live status message. A report sent through Telegram keeps the id of
-- the one bot message that is edited as its status moves; the chat is the patient's link.

-- The ALTER on reports checks its rows through the forced RLS policy, which raises on an unset
-- tenant. A nil tenant matches no row (as in 005, 007 and 008); the new column is nullable.
SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000000', true);

ALTER TABLE reports ADD COLUMN status_message_id bigint;
