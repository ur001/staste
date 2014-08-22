import datetime
import itertools

from django.conf import settings

from staste import redis, UNIQUE, CHOICES
from staste.dateaxis import DATE_AXIS


class MetricaValues(object):
    """
    A representation of a subset of Metrica statistical values
    Used for filtering
    """
    def __init__(self, metrica, timespan=None, filter=None):
        """Constructor. You probably don't want to call it directly"""
        self.metrica = metrica
        self._timespan = timespan or {}
        self._filter = filter or {}

        # we should do it now to raise an error eagerly
        tp_id = self.metrica.date_axis.timespan_to_id(**self._timespan)
        self._hash_key = u'%s:%s' % (self.metrica.key_prefix(), tp_id)
        self._hash_field_id = self.metrica.hash_field_id(**self._filter)

    # FILTERING
    def timespan(self, **kwargs):
        """Filter by timespan. Returns a new MetricaValues object"""

        tp = dict(self._timespan, **kwargs)
        return self.__class__(self.metrica, timespan=tp, filter=self._filter)

    def filter(self, **kwargs):
        fl = dict(self._filter, **kwargs)
        return self.__class__(self.metrica, timespan=self._timespan, filter=fl)

    def unique(self, is_unique=True):
        """Adds unique filter"""
        return self.filter(unique=is_unique)

    # GETTING VALUES
    def total(self):
        """Total events count in the subset"""
        return int(redis.hget(self._hash_key, self._hash_field_id) or 0) / self.metrica.multiplier

    def timeserie(self, since, until, scale=None, _hash_key_postfix='', _mult=None):
        mult = _mult or self.metrica.multiplier
        prefix = self.metrica.key_prefix()
        ts_points = self.metrica.date_axis.timeserie(since, until, scale)
        points = []
        pipe = redis.pipeline(transaction=False)

        for point, tp_id in ts_points:
            points.append(point)
            hash_key = u'%s:%s%s' % (prefix, tp_id, _hash_key_postfix)
            pipe.hget(hash_key, self._hash_field_id)

        values = pipe.execute()
        return zip(points, [int(v or 0) / mult for v in values])

    def iterate(self, axis=None):
        """
        Iterates on a MetricaValues set. Returns a list of (key, value) tuples.
        If axis is not specified, iterates on the next scale of a date axis.
        I.e. mymetric.timespan(year=2011).iterate() will iterate months.
        """
        if not axis:
            return self.iterate_on_dateaxis()

        return self._iterate(axis, self._hash_key, self.metrica.multiplier)

    def _iterate(self, axis, _hash_key, mult):
        keys = self.metrica.choices(axis, self._filter.get(axis, None))
        pipe = redis.pipeline(transaction=False)

        for key in keys:
            fl = dict(self._filter, **{axis: key})
            hash_field_id = self.metrica.hash_field_id(**fl)
            pipe.hget(_hash_key, hash_field_id)

        values = pipe.execute()
        return zip(keys, [int(v or 0) / mult for v in values])

    def iterate_on_dateaxis(self):
        """
        Iterates on the next scale of a date axis.
        I.e. mymetric.timespan(year=2011).iterate() will iterate months
        """
        return self._iterate_on_dateaxis('', self.metrica.multiplier)

    def _iterate_on_dateaxis(self, _hash_key_postfix, mult):
        prefix = self.metrica.key_prefix()
        keys = []
        pipe = redis.pipeline(transaction=False)

        for key, tp_id in self.metrica.date_axis.iterate(self):
            keys.append(key)
            hash_key = u'%s:%s' % (prefix, tp_id) + _hash_key_postfix
            pipe.hget(hash_key, self._hash_field_id)

        values = pipe.execute()
        return zip(keys, [int(v or 0) / mult for v in values])


class Metrica(object):
    """
    Metrica is some class of events you want to count, like "site visits".
    Metrica is actually a space of all such countable events.

    It consists of Axes, which represent some parameters of an event: for example, a page URL,
    or whether the visitor was logged in. Please take a look at staste.axes.Axis.

    Every time the event happens, you call Metrica.kick() function with all the parameters for all axes specified.
    """
    values_class = MetricaValues

    def __init__(self, name, axes, multiplier=None):
        """
        Constructor of a Metrica

        name - should be a unique (among your metrics) string, it will be used in Redis identifiers (lots of them)
        axes - a list/iterable of tuples: (keyword, staste.axes.Axis object). can be empty
        multiplier - you can multiply all values you provide.
        it's useful since Redis does not understand floating point increments.
        (all totals() will be divided back by this)
        """
        self.name = str(name)
        self.axes = list(axes)
        self.date_axis = DATE_AXIS
        self.multiplier = float(multiplier) if multiplier else 1
        # don't produce float output in the simple case

    def kick(self, value=1, date=None, unique=None, **kwargs):
        """
        Registers an event with parameters (for each of axis)
        unique - key for event unique (session_id, user_id , etc.)
        """
        date = date or datetime.datetime.now()
        value = int(self.multiplier * value)
        
        hash_key_prefix = self.key_prefix()

        choices_sets_to_append = []
        hash_field_id_parts = []
        unique_hash_field_id = self.hash_field_id(**kwargs)  # build field hash for unique check

        for axis_kw, axis in self.axes:
            param_value = kwargs.pop(axis_kw, None)
            
            hash_field_id_parts.append(
                list(axis.get_field_id_parts(param_value))
            )

            if axis.store_choice:
                for key_postfix, choice in axis.choices_from_value(param_value):
                    choice_key_parts = (CHOICES, axis_kw, key_postfix) if key_postfix else (CHOICES, axis_kw)
                    choices_sets_to_append.append((u':'.join(choice_key_parts), choice))
                    
        if kwargs:
            raise TypeError("Invalid kwargs left: %s" % kwargs)

        choices_sets_to_append = filter(None, choices_sets_to_append)
            
        # Here we go: bumping all counters out there
        pipe = redis.pipeline(transaction=False)

        for date_scale in self.date_axis.scales(date):
            hash_key = u'%s:%s' % (hash_key_prefix, date_scale.id)
            # Register event with given kwargs and determine is it unique
            is_unique = self.register_unique(hash_key, unique_hash_field_id, unique) if unique else False
            
            for parts in itertools.product(*hash_field_id_parts):
                hash_field_id = u':'.join(parts)

                self._increment(pipe, hash_key, hash_field_id, value, is_unique=is_unique)
            
            if date_scale.expiration:
                pipe.expire(hash_key, date_scale.expiration)

            if date_scale.store:
                choices_sets_to_append.append((date_scale.store, date_scale.value))

        for key, s_value in choices_sets_to_append:
            pipe.sadd(u'%s:%s' % (hash_key_prefix, key), s_value)

        pipe.execute()

    def choices(self, axis_kw, choices_filter=None):
        return dict(self.axes)[axis_kw].get_choices(
            self.key_for_axis_choices(axis_kw), choices_filter=choices_filter
        )

    # STATISTICS
    def values(self):
        """Returns a MetricaValues object for all the data out there"""
        return self.values_class(self)

    def __getattr__(self, attr, *args):
        """
        If no attr in Metrica try to find it in MetricaValues
        """
        try:
            return getattr(self.__class__, attr, *args)
        except AttributeError:
            return getattr(self.values(), attr, *args)

    # UTILS
    def key_prefix(self):
        metrics_prefix = settings.STASTE_METRICS_PREFIX
        return u'%s:%s' % (metrics_prefix, self.name)

    def hash_field_id(self, **kwargs):
        hash_field_id_parts = []
        is_unique = kwargs.pop('unique', False)
        
        for axis_kw, axis in self.axes:
            hash_field_id_parts.append(
                axis.get_field_main_id(kwargs.pop(axis_kw, None))
            )

        if kwargs:
            raise TypeError("Invalid kwargs left: %s" % kwargs)

        hash_field_id = u':'.join(hash_field_id_parts)
        return hash_field_id if not is_unique else self.unique_hash_field_id(hash_field_id)

    def get_axis(self, axis_kw):
        return dict(self.axes)[axis_kw]

    def key_for_axis_choices(self, axis_kw):
        return u'%s:%s:%s' % (self.key_prefix(), CHOICES, axis_kw)

    @staticmethod
    def unique_hash_field_id(hash_field_id):
        return u"{}:{}".format(hash_field_id, UNIQUE)

    def register_unique(self, hash_key_prefix, hash_field_id, unique):
        """
        Register unique for given hash_key_prefix and hash_field_id
        Return True if it the first hit, False otherwise
        """
        unique_key = u"{}:{}".format(hash_key_prefix, UNIQUE)
        value = u"{}:{}".format(hash_field_id, unique)
        return bool(redis.pfadd(unique_key, value))

    def _increment(self, pipe, hash_key, hash_field_id, value, is_unique=False):
        pipe.hincrby(hash_key, hash_field_id, value)
        if is_unique:
            pipe.hincrby(hash_key, self.unique_hash_field_id(hash_field_id), value)


class AveragedMetricaValues(MetricaValues):
    def average(self):
        return self.total() / self.count()

    def count(self):
        return int(redis.hget(u'%s:__len__' % self._hash_key, self._hash_field_id) or 0)

    def iterate_counts(self, axis=None):
        if not axis:
            return self._iterate_on_dateaxis(u':__len__', 1)

        hash_key = u'%s:__len__' % self._hash_key

        return self._iterate(axis, hash_key, 1)

    def iterate_averages(self, axis=None):
        vals = self.iterate(axis)
        counts = self.iterate_counts(axis)

        for (k1, v1), (k2, v2) in zip(vals, counts):
            assert k1 == k2

            if not v2:
                yield k1, None
            else:
                yield k1, v1 / v2

    def timeserie_counts(self, since, until, scale=None):
        return self.timeserie(since, until, scale, _hash_key_postfix=':__len__', _mult=1)

    def timeserie_counts_and_averages(self, since, until, scale=None):
        vals = self.timeserie(since, until, scale)
        counts = self.timeserie_counts(since, until, scale)

        for (k1, total), (k2, count) in zip(vals, counts):
            assert k1 == k2

            try:
                avg = total / count
            except ZeroDivisionError:
                avg = 0

            yield k1, count, avg

    def timeserie_averages(self, since, until, scale=None):
        count_avgs = self.timeserie_counts_and_averages(self, since, until, scale)
        for k, count, avg in count_avgs:
            yield k, avg


class AveragedMetrica(Metrica):
    """
    AveragedMetrica works like a normal metrica, but also stores counts of the events.
    So you can ask for .average or .count
    """
    values_class = AveragedMetricaValues

    def _increment(self, pipe, hash_key, hash_field_id, value, is_unique=False):
        """
        WARNING: unique for AverageMetrica not supports now!
        """
        super(AveragedMetrica, self)._increment(pipe, hash_key, hash_field_id, value)
        pipe.hincrby(u'%s:__len__' % hash_key, hash_field_id, 1)