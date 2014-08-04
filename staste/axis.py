from staste import redis


class Axis(object):
    def __init__(self, choices=None, value_type=str):
        self.choices = choices
        self.store_choice = self.choices is None  # Need store choices in Redis
        self.value_type = value_type

    def value_to_string(self, value):
        """Encode axis value to string"""
        return str(value)

    def value_from_string(self, value):
        """Decode axis value from string"""
        return self.value_type(value)

    def get_field_id_parts(self, value):
        if self.choices is not None and value not in self.choices:
            raise ValueError('Invalid value: {}, choices are: {}'.format(value, self.choices))
        
        return ['__all__', self.value_to_string(value)]

    def get_field_main_id(self, value):
        if not value:
            return '__all__'

        return self.value_to_string(value)

    def get_choices(self, key):
        return map(
            self.value_from_string,
            self.choices or redis.smembers(key)
        )


class StoredChoiceAxis(Axis):
    pass


class GenericObjectAxis(Axis):
    """
    Axis for generic object (object type, object id)
    Allow pass tuple type/id in metrica.kick() and filter by object type or both type/id

    Example:
        metrica = Metrica(name='test', axes=[('obj', GenericObjectAxis()), ('event', Axis())])
        metrica.kick(obj=('city', 1324), event='view')
        metrica.kick(obj=('experience', 1234), event='click')
        metrica.kick(obj=('experience', 1111), event='click')

        metrica.values().filter(obj=('experience', 1234)).iterate('event')  # Filter by type/id
        metrica.values().filter(obj='experience').iterate('event')  # Filter by type only
    """
    def __init__(self):
        super(GenericObjectAxis, self).__init__(value_type=tuple)

    def value_to_string(self, value):
        if isinstance(value, tuple):
            return '{}.{}'.format(*value)
        elif isinstance(value, basestring):
            return value
        else:
            raise ValueError('Invalid value: {}, only tuple (type, id) or string object type is allowed'.format(value))

    def value_from_string(self, value):
        """Decode axis value from string"""
        obj_type, obj_id = value.split('.')
        return obj_type, int(obj_id)

    def get_field_id_parts(self, value):
        # Value is tuple (string object type, object id)
        # We want to see statistics for concrete object, object type or all
        # Example ['__all__', 'experience', 'experience.1234']
        return ['__all__', value[0], '{}.{}'.format(*value)]