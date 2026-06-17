#!/usr/bin/env python3
"""
Реализация сохранения состояния в Agent Systems
Стек: Python, Redis, PostgreSQL, DSPy
"""

import json
import hashlib
from typing import Dict, List, Any, Optional
import redis
import psycopg2
from datetime import datetime
import math


# ============================================================================
# 1. CLASS SESSION STATE MANAGEMENT
# ============================================================================

class SessionState:
    """Класс для хранения и управления состоянием сессии диалога"""
    
    def __init__(self, user_id: str, session_id: str):
        self.user_id = user_id
        self.session_id = session_id
        self.created_at = datetime.now()
        self.last_updated = datetime.now()
        self.messages: List[Dict[str, Any]] = []
        self.agent_states: Dict[str, Any] = {}
        self.context_vector: List[float] = []  # Для векторного поиска
        self.state_version = 0
        self.is_active = True
    
    def add_message(self, role: str, content: str, metadata: Optional[Dict] = None):
        """Добавить сообщение в историю диалога"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.messages.append(message)
        self.update_state()
    
    def update_state(self):
        """Обновить векторное представление состояния"""
        if self.messages:
            # Превращаем последние сообщения в эмбеддинг
            context_text = " ".join([m["content"] for m in self.messages[-5:]])
            self.context_vector = self._embed_context(context_text)
    
    def _embed_context(self, context: str) -> List[float]:
        """Эмуляция векторного эмбеддинга (в реальности используем sentence-transformers)"""
        # В реальном проекте здесь используется модель типа sentence-transformers
        # Для примера генерируем псевдо-эмбеддинг
        return [hash(str(context) + str(i)) % 256 for i in range(128)]
    
    def get_summary(self) -> str:
        """Получить краткое описание состояния"""
        return f"Session {self.session_id} (User: {self.user_id}) - {len(self.messages)} сообщений"
    
    def save_to_redis(self, redis_client: redis.Redis):
        """Сохранить состояние в Redis"""
        key = f"agent_session:{self.session_id}"
        data = {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "messages": self.messages,
            "agent_states": self.agent_states,
            "context_vector": self.context_vector,
            "state_version": self.state_version,
            "is_active": self.is_active
        }
        redis_client.setex(key, 86400 * 7, json.dumps(data))
    
    def load_from_redis(self, redis_client: redis.Redis, session_id: str) -> Optional['SessionState']:
        """Загрузить состояние из Redis"""
        key = f"agent_session:{session_id}"
        data = redis_client.get(key)
        if data:
            state_data = json.loads(data)
            session = SessionState(
                user_id=state_data["user_id"],
                session_id=state_data["session_id"]
            )
            session.messages = state_data["messages"]
            session.agent_states = state_data["agent_states"]
            session.context_vector = state_data["context_vector"]
            session.state_version = state_data["state_version"]
            session.is_active = state_data["is_active"]
            session.last_updated = datetime.fromisoformat(state_data["last_updated"])
            return session
        return None
    
    def delete_from_redis(self, redis_client: redis.Redis):
        """Удалить состояние из Redis"""
        key = f"agent_session:{self.session_id}"
        redis_client.delete(key)


# ============================================================================
# 2. DATABASE STATE MANAGER
# ============================================================================

class DatabaseStateManager:
    """Управление состоянием через SQL базу данных"""
    
    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config
        self.conn = None
    
    def connect(self):
        """Подключиться к БД"""
        self.conn = psycopg2.connect(**self.db_config)
    
    def create_tables(self):
        """Создать таблицы для хранения состояний"""
        cursor = self.conn.cursor()
        
        # Таблица сессий
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id VARCHAR(255) PRIMARY KEY,
                user_id VARCHAR(255),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                state_version INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        
        # Таблица сообщений
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(255),
                role VARCHAR(50),
                content TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata JSONB,
                FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id)
            )
        """)
        
        # Таблица агентов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_states (
                agent_id VARCHAR(255),
                session_id VARCHAR(255),
                state JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id)
            )
        """)
        
        # Таблица контекста для векторного поиска
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_context (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(255),
                embedding_vector VECTOR(768),
                context_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("COMMIT")
    
    def save_session(self, session: SessionState):
        """Сохранить сессию в БД"""
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        
        # Обновить сессию
        cursor.execute("""
            UPDATE agent_sessions 
            SET user_id = %(user_id)s,
                last_updated = %(last_updated)s,
                state_version = %(state_version)s,
                is_active = %(is_active)s
            WHERE session_id = %(session_id)s
        """, {
            "user_id": session.user_id,
            "session_id": session.session_id,
            "last_updated": session.last_updated.isoformat(),
            "state_version": session.state_version,
            "is_active": session.is_active
        })
        
        # Вставить последнее сообщение
        last_msg = session.messages[-1]
        cursor.execute("""
            INSERT INTO agent_messages (session_id, role, content, timestamp, metadata)
            VALUES (%(session_id)s, %(role)s, %(content)s, %(timestamp)s, %(metadata)s)
        """, {
            "session_id": session.session_id,
            "role": last_msg["role"],
            "content": last_msg["content"],
            "timestamp": last_msg["timestamp"],
            "metadata": json.dumps(last_msg.get("metadata", {}))
        })
        
        # Сохранить состояния агентов
        for agent_id, agent_state in session.agent_states.items():
            cursor.execute("""
                INSERT INTO agent_states (agent_id, session_id, state, updated_at)
                VALUES (%(agent_id)s, %(session_id)s, %(state)s, %(updated_at)s)
            """, {
                "agent_id": agent_id,
                "session_id": session.session_id,
                "state": json.dumps(agent_state),
                "updated_at": session.last_updated.isoformat()
            })
        
        cursor.execute("COMMIT")
    
    def load_session(self, session_id: str) -> Optional[SessionState]:
        """Загрузить сессию из БД"""
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT session_id, user_id, created_at, last_updated, state_version, is_active
            FROM agent_sessions
            WHERE session_id = %(session_id)s
        """, {"session_id": session_id})
        
        row = cursor.fetchone()
        if not row:
            return None
        
        session = SessionState(
            user_id=row[1],
            session_id=row[0]
        )
        session.state_version = row[3]
        session.is_active = row[4]
        session.last_updated = datetime.fromisoformat(row[2])
        session.created_at = datetime.fromisoformat(row[1])
        
        # Загрузить сообщения
        cursor.execute("""
            SELECT role, content, timestamp, metadata
            FROM agent_messages
            WHERE session_id = %(session_id)s
            ORDER BY id ASC
        """, {"session_id": session_id})
        
        for row in cursor.fetchall():
            message = {
                "role": row[0],
                "content": row[1],
                "timestamp": row[2],
                "metadata": json.loads(row[3]) if row[3] else {}
            }
            session.messages.append(message)
        
        # Загрузить состояния агентов
        cursor.execute("""
            SELECT agent_id, state, updated_at
            FROM agent_states
            WHERE session_id = %(session_id)s
        """, {"session_id": session_id})
        
        for row in cursor.fetchall():
            agent_state = json.loads(row[1])
            session.agent_states[row[0]] = agent_state
        
        return session
    
    def search_by_context(self, query: str) -> List[SessionState]:
        """Поиск сессий по контексту (упрощенный пример)"""
        if not self.conn:
            self.connect()
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT session_id FROM agent_context
            WHERE embedding_vector IS NOT NULL
            LIMIT 10
        """)
        
        results = []
        for row in cursor.fetchall():
            session_id = row[0]
            session = self.load_session(session_id)
            if session:
                results.append(session)
        
        return results


# ============================================================================
# 3. AGENT ORCHESTRATOR
# ============================================================================

class AgentOrchestrator:
    """Оркестратор агентов с управлением состоянием"""
    
    def __init__(self, redis_client: redis.Redis, db_config: Dict[str, Any]):
        self.redis_client = redis_client
        self.db_manager = DatabaseStateManager(db_config)
        self.agents: Dict[str, Any] = {
            "research": {"role": "research", "tasks": []},
            "coding": {"role": "coding", "tasks": []},
            "review": {"role": "review", "tasks": []},
            "qa": {"role": "qa", "tasks": []}
        }
        self.active_sessions: Dict[str, SessionState] = {}
    
    def create_session(self, user_id: str, session_id: str) -> SessionState:
        """Создать новую сессию"""
        session = SessionState(user_id, session_id)
        session.save_to_redis(self.redis_client)
        
        # Сохранить в БД
        self.db_manager.save_session(session)
        self.active_sessions[session_id] = session
        return session
    
    def get_session(self, user_id: str) -> Optional[SessionState]:
        """Получить сессию пользователя"""
        # Попробовать получить из Redis
        session = self.redis_client.get(f"agent_session:{user_id}")
        if session:
            state_data = json.loads(session)
            return SessionState(
                user_id=user_id,
                session_id=state_data["session_id"]
            )
        
        # Попробовать получить из БД
        return self.db_manager.load_session(user_id)
    
    def add_agent(self, agent_id: str, agent_config: Dict[str, Any]):
        """Добавить агента к оркестратору"""
        self.agents[agent_id] = {
            "role": agent_config["role"],
            "tasks": agent_config.get("tasks", [])
        }
    
    def process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Обработать запрос с сохранением состояния"""
        # Получить или создать сессию
        session = self.get_session(request.get("user_id"))
        
        if not session:
            session = self.create_session(request.get("user_id"), f"session_{request.get('user_id', 'unknown')}")
        
        # Добавить сообщение
        session.add_message("user", json.dumps(request.get("message", "")))
        
        # Запустить агентов
        response = {"agent_responses": [], "conversation_history": []}
        
        for agent_id, agent_info in self.agents.items():
            # Выполнить задачу агента
            response["agent_responses"].append({
                "agent_id": agent_id,
                "response": f"Agent {agent_id} processed request"
            })
        
        # Сохранить обновленное состояние
        session.save_to_redis(self.redis_client)
        self.db_manager.save_session(session)
        
        return response
    
    def get_conversation_history(self, user_id: str) -> List[Dict[str, Any]]:
        """Получить историю диалога"""
        session = self.get_session(user_id)
        if session:
            return session.messages
        return []


# ============================================================================
# 4. DSPY-PROMPT OPTIMIZER
# ============================================================================

class DSPyPromptOptimizer:
    """Оптимизация промптов с использованием DSPy паттернов"""
    
    def __init__(self):
        # В реальном проекте здесь используются dspy.predictors и dspy.teleprompters
        pass
    
    def optimize_prompt(self, prompt: str, metric: str = "accuracy") -> str:
        """Автоматическая оптимизация промпта через DSPy"""
        # DSPy паттерны:
        # - Mipro (Multi-Input Predictive Optimization)
        # - Optuna (для гиперпараметров)
        # - Teleprompter (для поиска лучшего промпта)
        
        # Пример:
        # from dspy.primitives import InputPredictor
        # from dspy.teleprompters import Mipro
        # from dspy.databases import LLMDB
        
        # predictor = InputPredictor(query, context, output)
        # optimizer = Mipro(predictor, metric=metric)
        # best_prompt = optimizer.run(training_data)
        
        return prompt  # В реальном коде здесь DSPy оптимизация


# ============================================================================
# 5. COMPLETE EXAMPLE USAGE
# ============================================================================

def main():
    """Демонстрация работы системы сохранения состояния"""
    
    print("=" * 80)
    print("РЕАЛИЗАЦИЯ СОХРАНЕНИЯ СОСТОЯНИЯ В AGENT SYSTEMS")
    print("=" * 80)
    
    # Пример 1: Создание сессии
    print("\n" + "=" * 80)
    print("Пример 1: Создание сессии")
    print("=" * 80)
    
    user_id = "user_abc123"
    session_id = "session_12345"
    
    session = SessionState(user_id, session_id)
    session.add_message("user", "Привет, мне нужно помочь с кодом")
    session.add_message("assistant", "Конечно! Что нужно написать?")
    
    print(f"✓ Сессия создана: {session_id}")
    print(f"✓ Количество сообщений: {len(session.messages)}")
    print(f"✓ Сумма: {session.get_summary()}")
    
    # Пример 2: Векторное представление
    print("\n" + "=" * 80)
    print("Пример 2: Векторное представление контекста")
    print("=" * 80)
    
    print(f"Контекст для эмбеддинга: {session.context_vector}")
    print(f"Размерность вектора: {len(session.context_vector)}")
    
    # Пример 3: Управление состоянием агентов
    print("\n" + "=" * 80)
    print("Пример 3: Состояние агентов")
    print("=" * 80)
    
    session.agent_states = {
        "research": {"status": "idle", "tasks": []},
        "coding": {"status": "active", "tasks": ["analyze_code", "write_code"]},
        "review": {"status": "idle", "tasks": []},
        "qa": {"status": "idle", "tasks": []}
    }
    
    print(f"Состояние агентов: {json.dumps(session.agent_states, indent=2)}")
    
    # Пример 4: Версионность состояния
    print("\n" + "=" * 80)
    print("Пример 4: Версионность состояния (state version)")
    print("=" * 80)
    
    session.state_version = 2
    print(f"Текущая версия: {session.state_version}")
    print("Это позволяет отслеживать изменения и обновлять данные")
    
    # Пример 5: Активность сессии
    print("\n" + "=" * 80)
    print("Пример 5: Управление активностью сессии")
    print("=" * 80)
    
    session.is_active = True
    print(f"Сессия активна: {session.is_active}")
    session.is_active = False
    print(f"Сессия активна: {session.is_active} (для архивации)")
    
    # Пример 6: Временные метки
    print("\n" + "=" * 80)
    print("Пример 6: Временные метки")
    print("=" * 80)
    
    print(f"Создано: {session.created_at}")
    print(f"Последнее обновление: {session.last_updated}")
    
    # Пример 7: Вложенная структура
    print("\n" + "=" * 80)
    print("Пример 7: Вложенные сообщения")
    print("=" * 80)
    
    session.add_message("user", "Нужен Python скрипт для анализа данных")
    session.add_message("assistant", "Конечно! Вот пример скрипта:")
    session.add_message("user", "Спасибо!")
    
    for msg in session.messages:
        print(f"  [{msg['role']}] {msg['content']}")
    
    # Пример 8: Поиск по контексту
    print("\n" + "=" * 80)
    print("Пример 8: Поиск сессий по контексту")
    print("=" * 80)
    
    print("В реальном проекте используется векторный поиск в базе данных:")
    print("- ElasticSearch / OpenSearch")
    print("- Milvus / Pinecone")
    print("- PostgreSQL с векторными расширениями")
    
    print("\n" + "=" * 80)
    print("ПОЛНЫЙ КОД В ФАЙЛЕ: agent_state_preservation.py")
    print("Раскомментируйте реальные вызовы Redis и PostgreSQL для работы")
    print("=" * 80)


if __name__ == "__main__":
    main()
