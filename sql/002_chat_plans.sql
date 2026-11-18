-- Qwen Chat plans: how many questions a day and a week each person may ask, and requests to move to a bigger plan.
-- Run once as a MySQL admin after 001 (setup/bootstrap.sh runs both). Safe to re-run.
--   mysql -u root -p < sql/002_chat_plans.sql
-- The chat_api user's SELECT/INSERT/UPDATE/DELETE on chat_db.* already covers these tables.
--
-- There are no payments: a person asks for a plan on the Upgrade plan page and a super admin approves it
-- (Admin > Qwen Chat plans). Super admins themselves have no limit.

-- The plans. Change a limit with an UPDATE; NULL = no limit of that kind.
-- A question needs room in both: today's count (resets at midnight, India time) and this week's
-- (Monday to Sunday, resets Monday at midnight).
CREATE TABLE IF NOT EXISTS chat_db.plans (
  code              VARCHAR(32)   NOT NULL,
  name              VARCHAR(64)   NOT NULL,
  daily_questions   INT UNSIGNED  NULL,
  weekly_questions  INT UNSIGNED  NULL,
  description       VARCHAR(255)  NOT NULL DEFAULT '',
  sort_order        SMALLINT      NOT NULL DEFAULT 0,   -- low to high; an upgrade is a plan further down the list
  requestable       TINYINT(1)    NOT NULL DEFAULT 1,   -- 0 = only a super admin can give it
  PRIMARY KEY (code)
) ENGINE=InnoDB;

INSERT IGNORE INTO chat_db.plans (code, name, daily_questions, weekly_questions, description, sort_order, requestable) VALUES
  ('free', 'Free', 25,  100,  'Everyone starts here: enough to try Qwen Chat every day.', 10, 0),
  ('plus', 'Plus', 100, 400,  'For daily use: notes, hand reviews and code questions.',    20, 1),
  ('pro',  'Pro',  300, 1200, 'For heavy use through the day.',                            30, 1);

-- Each person's plan. No row = the Free plan.
CREATE TABLE IF NOT EXISTS chat_db.user_plans (
  user_id     BIGINT UNSIGNED NOT NULL,          -- auth_db user id (from nginx's X-Auth-User-Id)
  plan_code   VARCHAR(32)     NOT NULL,
  updated_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  updated_by  BIGINT UNSIGNED NULL,              -- the super admin who set it
  PRIMARY KEY (user_id),
  CONSTRAINT fk_user_plans_plan FOREIGN KEY (plan_code) REFERENCES chat_db.plans (code)
) ENGINE=InnoDB;

-- Questions asked per person per day (India time). Kept apart from the messages, so deleting a chat
-- does not give questions back. A week's count is the sum of its days.
CREATE TABLE IF NOT EXISTS chat_db.usage_daily (
  user_id            BIGINT UNSIGNED NOT NULL,
  day                DATE            NOT NULL,
  questions          INT UNSIGNED    NOT NULL DEFAULT 0,
  answer_ms          BIGINT UNSIGNED NOT NULL DEFAULT 0,   -- total time the model took to answer them
  first_question_at  DATETIME(3)     NULL,                 -- UTC; the usage page's "at this pace" uses it
  PRIMARY KEY (user_id, day)
) ENGINE=InnoDB;

-- "Please move me to Plus": one pending request per person at a time (a new one replaces it).
CREATE TABLE IF NOT EXISTS chat_db.plan_requests (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     BIGINT UNSIGNED NOT NULL,
  plan_code   VARCHAR(32)     NOT NULL,
  from_plan   VARCHAR(32)     NOT NULL,
  note        VARCHAR(500)    NULL,
  status      ENUM('pending', 'approved', 'declined', 'cancelled') NOT NULL DEFAULT 'pending',
  created_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  decided_at  DATETIME(3)     NULL,
  decided_by  BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  KEY idx_user_status (user_id, status),
  KEY idx_status_created (status, created_at),
  CONSTRAINT fk_plan_requests_plan FOREIGN KEY (plan_code) REFERENCES chat_db.plans (code)
) ENGINE=InnoDB;

-- Questions asked before this table existed, from the saved chats (MySQL here runs on India time)
INSERT IGNORE INTO chat_db.usage_daily (user_id, day, questions)
SELECT c.user_id, DATE(m.created_at), COUNT(*)
  FROM chat_db.messages m JOIN chat_db.conversations c ON c.id = m.conversation_id
 WHERE m.role = 'user'
 GROUP BY c.user_id, DATE(m.created_at);
