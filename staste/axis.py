from staste import redis, ALL


class Axis(object):
    def __init__(self, choices=None, value_type=str):
        self.choices = choices
        self.store_choice = self.choices is None  # Need store choices in Redis
        self.value_type = value_type

    def value_to_string(self, value):
        """Encode axis value to string"""
        return unicode(value)

    def value_from_string(self, value):
        """Decode axis value from string"""
        return self.value_type(unicode(value, 'utf-8'))

    def get_field_id_parts(self, value):
        if self.choices is not None and value not in self.choices:
            raise ValueError(u'Invalid value: {}, choices are: {}'.format(value, self.choices))
        
        return [ALL, self.value_to_string(value)] if value is not None else [ALL]

    def get_field_main_id(self, value):
        if not value:
            return ALL

        return self.value_to_string(value)

    def get_choices(self, key, **kwargs):
        return map(self.value_from_string, self.choices or redis.smembers(key))

    def choices_from_value(self, value):
        if value is not None:
            return [(u'', self.value_to_string(value))]
        else:
            return []


class StoredChoiceAxis(Axis):
    pass


class HierarchicalAxis(Axis):
    """
    Axis with tuple values.
    Allow pass tuples in metrica.kick() and filter() as axis values and see statistics
    for all hierarchical path slices. E.g. ALL, a, a/b and a/b/c for a/b/c

    Example:
        metrica = Metrica(name='test', axes=[('place', TreePathAxis()), ('event', Axis())])
        metrica.kick(place=('city', city_id), event='impression', id=experience_id)
        metrica.kick(place=('city_tag', city_id, tag_id), event='impression', id=experience_id)
        metrica.kick(place=('collection', collection_id), event='impression', id=experience_id)
        metrica.kick(place=('collection_city', collection_id, city_id), event='impression', id=experience_id)
        metrica.kick(place=('main_page', 'featured'), event='impression', id=experience_id)
        metrica.kick(place=('main_page', 'popular'), event='impression', id=experience_id)

        metrica.kick(place=('link', 'tripster.ru', 'question'), event='pageview', id=experience_id)
        metrica.kick(place=('link', 'livejournal.com', lj_username), event='pageview', id=experience_id)
        metrica.kick(place=('link', site_domain), event='pageview', id=experience_id)

        metrica.kick(place=('se', 'yandex'), event='pageview', id=experience_id)
        metrica.kick(place=('se', 'google'), event='pageview', id=experience_id)

        metrica.kick(place=('experience',), event='pageview', id=experience_id)

        metrica.filter(path=('city'), event='impression').total()
        metrica.filter(path=('city', city_id), event='impression').total()
        metrica.filter(path=('city_tag'), event='impression').total()
        metrica.filter(path=('city_tag', city_id), event='impression').total()
        metrica.filter(path=('city_tag', city_id, tag_id), event='impression').total()
    """
    def __init__(self):
        super(HierarchicalAxis, self).__init__(value_type=tuple)

    def value_to_string(self, value):
        if isinstance(value, (list, tuple)):
            return u'/'.join(map(unicode, value))
        else:
            return unicode(value)

    def value_from_string(self, value):
        """Decode axis value from string"""
        return tuple(unicode(value, 'utf-8').split(u'/'))

    def get_field_id_parts(self, value):
        """
        We want to see statistics for tree-path-axis on any deep
        Example ['__all__', 'city_tag', 'city_tag/city_id', 'city_tag/city_id/tag_id']
        :param value: tuple value
        :return: all possible axis path slices, includes ALL
        """
        parts = [ALL]
        if value is not None:
            path = u''
            for part in value:
                path += u'/' + unicode(part) if path else unicode(part)
                parts.append(path)

        return parts

    def get_choices(self, key, choices_filter=None):
        if choices_filter:
            key = u"{}:{}".format(key, self.value_to_string(choices_filter))
            choices = super(HierarchicalAxis, self).get_choices(key)
            return [choices_filter + (choice[0],) for choice in choices]
        else:
            return super(HierarchicalAxis, self).get_choices(key)

    def choices_from_value(self, value):
        if value is not None:
            return [
                (self.value_to_string(value[:n]), self.value_to_string(value[n]))
                for n in range(len(value))
            ]

        return super(HierarchicalAxis, self).choices_from_value(value)