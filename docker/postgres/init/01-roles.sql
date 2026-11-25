CREATE ROLE hc_owner LOGIN PASSWORD 'owner_dev' CREATEDB;
CREATE ROLE hc_app   LOGIN PASSWORD 'app_dev'   NOBYPASSRLS;
CREATE ROLE hc_graph LOGIN PASSWORD 'graph_dev' NOBYPASSRLS;
-- background worker: hc_app's grants plus one cross-tenant policy on jobs (003)
CREATE ROLE hc_worker LOGIN PASSWORD 'worker_dev' NOBYPASSRLS IN ROLE hc_app;
-- lets migrations (run as hc_owner) create the graph schema owned by hc_graph
GRANT hc_graph TO hc_owner;
CREATE DATABASE healthcare OWNER hc_owner;
