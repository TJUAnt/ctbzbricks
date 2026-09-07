-- name: PutPixelCatalog :exec
INSERT INTO pixel_2d.catalogs(hash,document) VALUES ($1,$2) ON CONFLICT DO NOTHING;
-- name: GetPixelCatalog :one
SELECT hash,document FROM pixel_2d.catalogs ORDER BY created_at DESC,hash DESC LIMIT 1;

-- name: ReservePixelBlob :exec
INSERT INTO pixel_2d.blobs(id,owner_id,object_key,bucket,kind,sha256,byte_size,content_type)
VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(id) DO NOTHING;
-- name: ReadyPixelBlob :exec
UPDATE pixel_2d.blobs SET status='ready' WHERE id=$1 AND owner_id=$2;
-- name: GetPixelBlob :one
SELECT id,owner_id,object_key,bucket,kind,sha256,byte_size,content_type,status FROM pixel_2d.blobs WHERE id=$1 AND owner_id=$2;

-- name: CreatePixelProject :exec
INSERT INTO pixel_2d.projects(id,owner_id,name,content_locale,source_name,source_blob_id,grid_width,grid_height,color_count)
VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9);
-- name: GetPixelProject :one
SELECT id,owner_id,name,content_locale,source_name,source_blob_id,grid_width,grid_height,color_count,current_revision_id,created_at
FROM pixel_2d.projects WHERE id=$1 AND owner_id=$2;
-- name: LockPixelProject :one
SELECT id,owner_id,name,content_locale,source_name,source_blob_id,grid_width,grid_height,color_count,current_revision_id,created_at
FROM pixel_2d.projects WHERE id=$1 AND owner_id=$2 FOR UPDATE;
-- name: AdvancePixelProject :execrows
UPDATE pixel_2d.projects SET current_revision_id=sqlc.arg(revision_id)
WHERE id=sqlc.arg(project_id) AND owner_id=sqlc.arg(owner_id)
AND current_revision_id IS NOT DISTINCT FROM sqlc.narg(parent_revision_id)::uuid;

-- name: CreatePixelRevision :exec
INSERT INTO pixel_2d.revisions(id,project_id,owner_id,parent_revision_id,input_blob_id,task_id,settings)
VALUES($1,$2,$3,$4,$5,$6,$7);
-- name: GetPixelRevision :one
SELECT id,project_id,owner_id,parent_revision_id,input_blob_id,task_id,document_blob_id,preview_blob_id,settings FROM pixel_2d.revisions WHERE id=$1 AND owner_id=$2;
-- name: CompletePixelRevision :execrows
UPDATE pixel_2d.revisions SET document_blob_id=$3,preview_blob_id=$4
WHERE id=$1 AND owner_id=$2 AND document_blob_id IS NULL;

-- 一条语句保证 count 与 rows 的可见性快照一致；页外像素/预览正文不参与查询。
-- name: ListPixelProjects :one
WITH selected_page AS MATERIALIZED (
 SELECT p.id,p.name,p.content_locale,p.source_name,p.grid_width,p.grid_height,p.color_count,p.created_at,p.current_revision_id
 FROM pixel_2d.projects p WHERE p.owner_id=sqlc.arg(owner_id)
 ORDER BY p.created_at DESC,p.id DESC LIMIT sqlc.arg(page_size) OFFSET sqlc.arg(page_offset)
), enriched AS (
 SELECT p.*,r.task_id,r.preview_blob_id,t.status AS task_status FROM selected_page p
 LEFT JOIN pixel_2d.revisions r ON r.id=p.current_revision_id
 LEFT JOIN component_repo.tasks t ON t.id=r.task_id
)
SELECT (SELECT count(*) FROM pixel_2d.projects p WHERE p.owner_id=sqlc.arg(owner_id))::bigint AS total,
COALESCE((SELECT jsonb_agg(to_jsonb(enriched) ORDER BY created_at DESC,id DESC) FROM enriched),'[]'::jsonb)::jsonb AS items;
