"""Persist one active quiz per user so retries and abandoned quizzes cannot add wins."""
import time
from title_core import record_event


def expire_round(connection, user_id):
    row = connection.execute('SELECT round_id,expires_at,resolved FROM george_quiz_rounds WHERE user_id=%s', (user_id,)).fetchone()
    if row and not row[2] and row[1] <= int(time.time()):
        resolve_round(connection, user_id, row[0], False)


def resolve_round(connection, user_id, round_id, correct_first):
    row = connection.execute('SELECT round_id,expires_at,resolved FROM george_quiz_rounds WHERE user_id=%s', (user_id,)).fetchone()
    if not row or row[0] != round_id or row[2]:
        return
    first = correct_first and row[1] > int(time.time())
    record_event(connection, user_id, f'quiz-streak:{round_id}', 'quiz_streak', correct_first=bool(first))
    connection.execute('UPDATE george_quiz_rounds SET resolved=1 WHERE user_id=%s AND round_id=%s', (user_id, round_id))


class QuizRounds:
    def start_quiz_round(self, user_id, round_id):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            row = conn.execute('SELECT round_id,expires_at,resolved FROM george_quiz_rounds WHERE user_id=%s', (user_id,)).fetchone()
            if row and row[0] >= round_id:
                return
            if row and not row[2]:
                resolve_round(conn, user_id, row[0], False)
            conn.execute('''INSERT INTO george_quiz_rounds(user_id,round_id,expires_at,resolved)
                VALUES (%s,%s,%s,0) ON CONFLICT(user_id) DO UPDATE SET
                round_id=EXCLUDED.round_id,expires_at=EXCLUDED.expires_at,resolved=0''', (user_id, round_id, int(time.time()) + 180))

    def resolve_quiz_round(self, user_id, round_id, correct_first):
        with self.connect() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(%s)', (user_id,))
            resolve_round(conn, user_id, round_id, correct_first)
