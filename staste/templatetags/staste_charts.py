from django import template
from django.utils.numberformat import format

register = template.Library()


@register.filter
def dotted_number(number):
    if type(number) == float:
        number = format(number, '.', 6)
    return number
    
