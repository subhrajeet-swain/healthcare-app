-- Phase 3.1: the messaging tables become channel-neutral (WhatsApp, then Telegram). Tables are
-- renamed in place: policies, grants and forced RLS follow them. Existing rows are WhatsApp.

-- The ALTERs on reports and chat_messages check their rows through the forced RLS policies,
-- which raise on an unset tenant. A nil tenant matches no row (as in 005 and 007); the new
-- checks only widen the old ones. Reverts at the end of the transaction.
SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000000', true);

ALTER TABLE wa_links RENAME TO channel_links;
ALTER TABLE wa_link_codes RENAME TO link_codes;
ALTER TABLE wa_inbound RENAME TO inbound_messages;
ALTER TABLE channel_links RENAME COLUMN wa_fp TO address_fp;
ALTER TABLE channel_links RENAME COLUMN wa_enc TO address_enc;

ALTER INDEX wa_link_codes_hash RENAME TO link_codes_hash;
ALTER INDEX wa_inbound_sender RENAME TO inbound_messages_sender;
ALTER TABLE channel_links RENAME CONSTRAINT wa_links_pkey TO channel_links_pkey;
ALTER TABLE channel_links RENAME CONSTRAINT wa_links_lang_check TO channel_links_lang_check;
ALTER TABLE channel_links
    RENAME CONSTRAINT wa_links_tenant_id_user_id_fkey TO channel_links_tenant_id_user_id_fkey;
ALTER TABLE link_codes RENAME CONSTRAINT wa_link_codes_pkey TO link_codes_pkey;
ALTER TABLE link_codes RENAME CONSTRAINT wa_link_codes_lang_check TO link_codes_lang_check;
ALTER TABLE link_codes
    RENAME CONSTRAINT wa_link_codes_tenant_id_user_id_fkey TO link_codes_tenant_id_user_id_fkey;
ALTER TABLE inbound_messages RENAME CONSTRAINT wa_inbound_pkey TO inbound_messages_pkey;
ALTER TABLE inbound_messages
    RENAME CONSTRAINT wa_inbound_tenant_id_fkey TO inbound_messages_tenant_id_fkey;

-- One link per user and channel; one address per channel (the same number may be on two).
ALTER TABLE channel_links
    DROP CONSTRAINT wa_links_tenant_id_user_id_key,
    DROP CONSTRAINT wa_links_tenant_id_wa_fp_key,
    ADD COLUMN channel text NOT NULL DEFAULT 'whatsapp'
        CHECK (channel IN ('whatsapp', 'telegram'));
ALTER TABLE channel_links
    ALTER COLUMN channel DROP DEFAULT,
    ADD CONSTRAINT channel_links_user_channel_key UNIQUE (tenant_id, user_id, channel),
    ADD CONSTRAINT channel_links_address_key UNIQUE (tenant_id, channel, address_fp);

ALTER TABLE link_codes
    ADD COLUMN channel text NOT NULL DEFAULT 'whatsapp'
        CHECK (channel IN ('whatsapp', 'telegram'));
ALTER TABLE link_codes ALTER COLUMN channel DROP DEFAULT;

-- The outbox (ruling T4) holds reply text for a linked sender: user_id lets delete-my-data
-- remove it. Null for an unlinked sender (the reply is a fixed line, and there is no user).
ALTER TABLE inbound_messages
    ADD COLUMN user_id uuid,
    ADD FOREIGN KEY (tenant_id, user_id) REFERENCES users (tenant_id, id) ON DELETE CASCADE;

-- The lab's public phone for the urgent banner's call button (tenants has no RLS).
ALTER TABLE tenants ADD COLUMN phone text;

ALTER TABLE reports DROP CONSTRAINT reports_source_check;
ALTER TABLE reports
    ADD CONSTRAINT reports_source_check
    CHECK (source IN ('patient', 'lab', 'whatsapp', 'telegram'));

ALTER TABLE chat_messages DROP CONSTRAINT chat_messages_channel_check;
ALTER TABLE chat_messages
    ADD CONSTRAINT chat_messages_channel_check CHECK (channel IN ('web', 'whatsapp', 'telegram'));
