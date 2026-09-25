from flask_sqlalchemy import SQLAlchemy

# Shared Flask extensions. Imported by models and services; keeping db in its
# own module avoids circular imports between the app factory and the models.
db = SQLAlchemy()
