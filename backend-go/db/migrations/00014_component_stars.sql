-- +goose Up

-- Star 是个人收藏关系，不包含通知语义；旧 subscription 数据一次迁移后删除，避免长期双写。
CREATE TABLE component_repo.component_stars (
    actor_id uuid NOT NULL,
    component_id uuid NOT NULL REFERENCES component_repo.components(id) ON DELETE CASCADE,
    starred_at timestamptz NOT NULL DEFAULT now(),
    source text NOT NULL DEFAULT 'user_action',
    PRIMARY KEY (actor_id, component_id),
    CONSTRAINT component_stars_source_check CHECK (
        source IN ('user_action', 'subscription_migration')
    )
);

CREATE INDEX component_stars_actor_time_idx
    ON component_repo.component_stars (actor_id, starred_at DESC, component_id);
CREATE INDEX component_stars_component_idx
    ON component_repo.component_stars (component_id, actor_id);

INSERT INTO component_repo.component_stars (actor_id, component_id, starred_at, source)
SELECT owner_id, component_id, subscribed_at, 'subscription_migration'
FROM component_repo.component_subscriptions;

DROP TABLE component_repo.component_subscriptions;

ALTER TABLE component_repo.component_stars ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.component_stars FROM PUBLIC;

-- +goose Down

CREATE TABLE component_repo.component_subscriptions (
    owner_id uuid NOT NULL,
    component_id uuid NOT NULL REFERENCES component_repo.components(id) ON DELETE CASCADE,
    subscribed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, component_id)
);

CREATE INDEX component_subscriptions_component_idx
    ON component_repo.component_subscriptions (component_id, owner_id);

INSERT INTO component_repo.component_subscriptions (owner_id, component_id, subscribed_at)
SELECT actor_id, component_id, starred_at
FROM component_repo.component_stars;

DROP TABLE component_repo.component_stars;

ALTER TABLE component_repo.component_subscriptions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON component_repo.component_subscriptions FROM PUBLIC;
