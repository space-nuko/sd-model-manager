import simplejson
from sqlalchemy import TypeDecorator, types


class JSON(TypeDecorator):
    @property
    def python_type(self):
        return object

    impl = types.String

    def process_bind_param(self, value, dialect):
        return simplejson.dumps(value)

    def process_literal_param(self, value, dialect):
        return value

    def process_result_value(self, value, dialect):
        try:
            return simplejson.loads(value)
        except (ValueError, TypeError):
            return None
