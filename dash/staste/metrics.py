import datetime

from django.conf import settings

from staste import redis
from staste.axes import DATE_AXIS

class Metrica(object):
    """Metrica is some class of events you want to count, like "site visits".

    Metrica is actually a space of all such countable events.

    It consists of Axes, which represent some parameters of an event: for example, a page URL, or whether the visitor was logged in. Please take a look at staste.axes.Axis.

    Every time the event happens, you call Metrica.kick() function with all the parameters for all axes specified.
    """

    def __init__(self, name, axes):
        """Constructor of a Metrica

        name - should be a unique (among your metrics) string, it will be used in Redis identifiers (lots of them)
        axes - a list of staste.axes.Axis objects. can be empty"""
        self.name = str(name)
        self.axes = list(axes)
        self.date_axis = DATE_AXIS
        

    def kick(self, date=None, **kwargs):
        """Registers an event with parameters (for each of axis)"""
        date = date or datetime.datetime.now()
        
        hash_key_prefix = self.key_prefix()
        hash_field_id = ''


        # Here we go: bumping all counters
        pipe = redis.pipeline(transaction=False)

        for scale in self.date_axis.scales(date):
            hash_key = '%s:%s' % (hash_key_prefix, scale.id)

            pipe.hincrby(hash_key, hash_field_id, 1)
            
            if scale.expiration:
                pipe.expire(hash_key, scale.expiration)

            if scale.store:
                set_key = '%s:%s' % (hash_key_prefix, scale.store)
                pipe.sadd(set_key, scale.value)

        pipe.execute()
        

    def timespan(self, **kwargs):
        """Returns an MetricaValues object limited to the spefic period in time

        Please keep in mind that the timespan can't be arbitraty and is limited to years, months, days and hours"""
        mv = MetricaValues(self)
        return mv.timespan(**kwargs)

    # UTILS

    def key_prefix(self):
        metrics_prefix = settings.STASTE_METRICS_PREFIX
        
        return '%s:%s' % (metrics_prefix, self.name)





class MetricaValues(object):
    """A representation of a subset of Metrica statistical values

    Used for filtering"""
    
    def __init__(self, metrica, timespan=None):
        """Constructor. You probably don't want to call it directly"""
        self.metrica = metrica
        self._timespan = timespan or {}

        # we should do it now to raise an error eagerly
        tp_id = self.metrica.date_axis.timespan_to_id(**self._timespan)
        self._hash_key = '%s:%s' % (self.metrica.key_prefix(),
                                    tp_id)
        self._hash_field_id = ''


    # FILTERING
        
    def timespan(self, **kwargs):
        """Filter by timespan. Returns a new MetricaValues object"""
        tp = dict(self._timespan, **kwargs)
        return MetricaValues(self.metrica, timespan=tp)

    # GETTING VALUES

    def total(self):
        """Total events count in the subset"""
        
        return int(redis.hget(self._hash_key, self._hash_field_id) or 0)

    def iterate(self):
        prefix = self.metrica.key_prefix()

        pipe = redis.pipeline(transaction=False)

        keys = []

        for key, tp_id in self.metrica.date_axis.iterate(self):
            keys.append(key)
            
            hash_key = '%s:%s' % (prefix, tp_id)
            
            pipe.hget(hash_key, self._hash_field_id)

        return zip(keys, [int(v or 0) for v in pipe.execute()])
            
            
        
