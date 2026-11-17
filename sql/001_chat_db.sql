-- Qwen Chat history (chat-api): each signed-in person's conversations and their messages.
-- Run once by setup/bootstrap.sh (as a MySQL admin). Safe to re-run.
--
-- People are identified by their auth_db user id, which nginx passes to chat-api as X-Auth-User-Id
-- after sign-in. This database holds no account data and has no foreign key to auth_db.

CREATE DATABASE IF NOT EXISTS chat_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- One row per conversation. id is random (uuid4 hex), so ids cannot be guessed or counted.
CREATE TABLE IF NOT EXISTS chat_db.conversations (
  id          CHAR(32)        NOT NULL,
  user_id     BIGINT UNSIGNED NOT NULL,
  title       VARCHAR(200)    NOT NULL,
  created_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),   -- last message; the list is newest first
  PRIMARY KEY (id),
  KEY idx_user_updated (user_id, updated_at)
) ENGINE=InnoDB;

-- Every question and answer, in order. Deleting a conversation deletes its messages.
CREATE TABLE IF NOT EXISTS chat_db.messages (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  conversation_id  CHAR(32)        NOT NULL,
  role             ENUM('user', 'assistant') NOT NULL,
  content          MEDIUMTEXT      NOT NULL,
  model            VARCHAR(64)     NULL,       -- assistant replies: the model that answered
  elapsed_ms       INT UNSIGNED    NULL,       -- assistant replies: how long the answer took
  created_at       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_conversation (conversation_id, id),
  CONSTRAINT fk_messages_conversation FOREIGN KEY (conversation_id)
    REFERENCES chat_db.conversations (id) ON DELETE CASCADE
) ENGINE=InnoDB;
