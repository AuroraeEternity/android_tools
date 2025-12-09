from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()


class Package(Base):
    __tablename__ = 'packages'
    id = Column(Integer, primary_key=True)
    package_name = Column(String, unique=True, nullable=False)
    activity_name = Column(String, nullable=True)
    last_used = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "package_name": self.package_name,
            "activity_name": self.activity_name,
            "last_used": self.last_used.isoformat() if self.last_used else None
        }


class EventExpectation(Base):
    __tablename__ = 'event_expectations'
    id = Column(Integer, primary_key=True)
    keyword = Column(String, nullable=False)
    description = Column(String, nullable=True)
    exact_match = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "keyword": self.keyword,
            "description": self.description,
            "exact_match": bool(self.exact_match),
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


engine = create_engine('sqlite:///packages.db', connect_args={'check_same_thread': False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    # 初始化默认数据
    _init_default_packages()


def _init_default_packages():
    """初始化插入默认的包名"""
    default_pkg = "com.solvely.photo.math.solver.calculator.ai"
    
    # 检查是否已存在
    db = SessionLocal()
    try:
        exists = db.query(Package).filter_by(package_name=default_pkg).first()
        if not exists:
            print(f"Inserting default package: {default_pkg}")
            new_pkg = Package(package_name=default_pkg, activity_name=None)
            db.add(new_pkg)
            db.commit()
    except Exception as e:
        print(f"Error initializing default package: {e}")
        db.rollback()
    finally:
        db.close()


def get_packages(limit=20):
    db = SessionLocal()
    try:
        packages = db.query(Package).order_by(Package.last_used.desc()).limit(limit).all()
        return [p.to_dict() for p in packages]
    finally:
        db.close()


def add_or_update_package(package_name, activity_name=None):
    db = SessionLocal()
    try:
        existing = db.query(Package).filter_by(package_name=package_name).first()
        if existing:
            existing.last_used = datetime.utcnow()
            if activity_name:
                existing.activity_name = activity_name
        else:
            new_pkg = Package(package_name=package_name, activity_name=activity_name)
            db.add(new_pkg)
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def get_event_expectations():
    db = SessionLocal()
    try:
        rules = db.query(EventExpectation).order_by(EventExpectation.id.asc()).all()
        return [rule.to_dict() for rule in rules]
    finally:
        db.close()


def replace_event_expectations(rules):
    """
    用新的规则列表覆盖现有的埋点期望
    :param rules: [{"keyword": "...", "description": "...", "exact_match": True}]
    """
    db = SessionLocal()
    try:
        db.query(EventExpectation).delete()
        for item in rules:
            keyword = (item.get('keyword') or '').strip()
            if not keyword:
                continue
            rule = EventExpectation(
                keyword=keyword,
                description=item.get('description'),
                exact_match=bool(item.get('exact_match', True))
            )
            db.add(rule)
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
