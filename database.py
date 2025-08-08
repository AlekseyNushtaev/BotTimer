from sqlalchemy import create_engine, Column, String
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class Chat(Base):
    __tablename__ = 'chats'
    chat_id = Column(String, primary_key=True)

engine = create_engine('sqlite:///chats.db')
Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)

def add_chat(chat_id: str):
    session = Session()
    # Используем merge вместо add для предотвращения дубликатов
    session.merge(Chat(chat_id=chat_id))
    session.commit()
    session.close()

def remove_chat(chat_id: str):
    session = Session()
    chat = session.get(Chat, chat_id)
    if chat:
        session.delete(chat)
        session.commit()
    session.close()

def get_all_chats() -> list[str]:
    session = Session()
    chats = session.query(Chat.chat_id).all()
    session.close()
    return [chat[0] for chat in chats]