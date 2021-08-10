from django.db.models import fields
from rest_framework.parsers import BaseParser
from rest_framework import serializers
from datetime import date, datetime, timedelta, timezone
from .models import GameRecord
import re
import itertools
import functools
import operator
import json

required_fields = [
    'version',
    'name',
    'death',
    'turns',
    'role',
    'starttime',
    'endtime',
]
filtered_fields = [
    'flags',
    'conduct',
    'achieve',
    'tnntachieve0',
    'tnntachieve1',
    'tnntachieve2',
    'tnntachieve3',
]
flag_bits = {
    'wizard': 0x1,
    'explore': 0x2,
    'bonesless': 0x4,
}
achieve_ascended = 0x100

try:
    file = open('scoreboard/data/conducts.json',)
    conducts_map = json.load(file)
    file.close()
except:
    print("could not open scoreboard/data/conducts.json for reading")

try:
    file = open('scoreboard/data/achievements.json',)
    achievements_map = json.load(file)
    file.close()
except:
    print("could not open scoreboard/data/achievements.json for reading")

def flatten(a):
    while isinstance(a, list) and len(a) and isinstance(a[0], list):
        a = functools.reduce(operator.concat, a)
    return a

class XlogParser(BaseParser):
    delimiter = '\t'
    separator = '='

    def __convert__(self, value):
        if re.match('^[0-9]+$', value) or re.match('^0x[0-9a-fA-F]+$', value):
            return int(value, 0)
        else:
            return value

    def parse(self, stream, media_type=None, parser_context=None):
        """
        Parse xlogfile data into python primitive types.
        This step is required before the XlogListSerializer and XlogRecordSerializer
        can do their jobs.
        Input: filehandle stream e.g. from fopen('foo.xlog',)
        Output: list of dicts xlog_entry, where
        xlog entry = { key: val, ... } for each xlogfile field `<key>=<val>`, where
        each numeric value is converted to an integer with int(val, 0). This could
        possibly cause issues with fields where we're using bigint in the database...
        """
        return [
            {
                k: self.__convert__(v)
                for k, v in [
                    i.split(self.separator)
                    for i in line.rstrip().split(self.delimiter)
                ]
            }
            for line in stream.readlines()
        ]

class TimeStampField(serializers.DateTimeField):
    def to_representation(self, value):
        return int(value.timestamp())
    
    def to_internal_value(self, value):
        return datetime.fromtimestamp(value, timezone.utc)

class GameSerializer(serializers.ModelSerializer):
    character = serializers.SerializerMethodField()
    dlvl = serializers.SerializerMethodField()
    HP = serializers.SerializerMethodField()
    endtime = TimeStampField()
    realtime = serializers.SerializerMethodField()
    wallclock = serializers.SerializerMethodField()

    class Meta:
        model = GameRecord
        fields = ['server', 'variant', 'version', 'name', 'character', 'points', 'turns', 'realtime', 'wallclock', 'dlvl', 'HP', 'endtime', 'death']
    
    def get_character(self, obj):
        role = [obj.role, obj.race, obj.gender, obj.align]
        return '-'.join([i for i in role if i])
    
    def get_dlvl(self, obj):
        return '{}/{}'.format(obj.deathlev, obj.maxlvl)
    
    def get_HP(self, obj):
        return '{}/{}'.format(obj.hp, obj.maxhp)

    def get_realtime(self, obj):
        return obj.realtime.total_seconds()

    def get_wallclock(self, obj):
        return obj.wallclock.total_seconds()

class AscensionSerializer(GameSerializer):
    class Meta:
        model = GameRecord
        fields = ['server', 'variant', 'version', 'name', 'character', 'points', 'turns', 'realtime', 'wallclock', 'dlvl', 'HP', 'endtime', 'conducts']

class XlogListSerializer(serializers.ListSerializer):
    def create(self, validated_data):
        games = [GameRecord(**item) for item in validated_data]
        return GameRecord.objects.bulk_create(games)

class XlogRecordSerializer(serializers.ModelSerializer):
    starttime = TimeStampField()
    endtime = TimeStampField()
    server = serializers.SerializerMethodField()
    variant = serializers.SerializerMethodField()
    wallclock = serializers.SerializerMethodField()
    mode = serializers.SerializerMethodField()
    flags = serializers.IntegerField()
    conduct = serializers.IntegerField()
    achieve = serializers.IntegerField()
    tnntachieve0 = serializers.IntegerField()
    tnntachieve1 = serializers.IntegerField()
    tnntachieve2 = serializers.IntegerField()
    tnntachieve3 = serializers.IntegerField()

    class Meta:
        model = GameRecord
        list_serializer_class = XlogListSerializer
        fields = '__all__'
    
    def _mode(self, data):
        if 'flags' not in data:
            return
        flags = data['flags']
        if flags & flag_bits['wizard']:
            return 'wizard'
        elif flags & flag_bits['explore']:
            return 'explore'
        else:
            return 'normal'
    
    def _bonesless(self, data):
        if 'flags' not in data:
            return False
        flags = data['flags']
        if flags & flag_bits['bonesless']:
            return True
        return False
    
    def _conducts(self, data):
        return ','.join(flatten([[[val for _key, val in conducts_map[field][bit].items() ]
                for bit in itertools.filterfalse(lambda x: not int(x, 0) & data[field], conducts_map[field].keys()) ]
            for field in itertools.filterfalse(lambda key: key not in data, ['conduct', 'achieve']) ]))

    def _achievements(self, data):
        return ','.join(flatten([[[key for key, _val in achievements_map[field][bit].items() ]
                for bit in itertools.filterfalse(lambda x: not int(x, 0) & data[field], achievements_map[field].keys()) ]
            for field in itertools.filterfalse(lambda key: key not in data, ['achieve', 'tnntachieve0', 'tnntachieve1', 'tnntachieve2', 'tnntachieve3']) ]))
    
    def _won(self, data):
        if 'achieve' in data and data['achieve'] & achieve_ascended:
            return True
        elif data['death'] == 'ascended':
            return True
        else:
            return False
    
    def create(self, validated_data):
        return GameRecord.objects.create(**validated_data)
    
    def validate(self, data):
        data['server'] = self.context['server']
        data['variant'] = self.context['variant']
        for field in required_fields:
            if not field in data:
                raise serializers.ValidationError('missing required field')
        if data['endtime'] < data['starttime']:
            raise serializers.ValidationError('game cannot end before it has begun')
        data['wallclock'] = data['endtime'] - data['starttime']
        if data['wallclock'] < data['realtime']:
            raise serializers.ValidationError('wallclock time cannot be less than realtime')
        data['mode'] = self._mode(data)
        data['bonesless'] = self._bonesless(data)
        data['conducts'] = self._conducts(data)
        data['nconducts'] = len(data['conducts'].split(','))
        data['achievements'] = self._achievements(data)
        data['won'] = self._won(data)
        return {
            field: data[field]
            for field in itertools.filterfalse(lambda k: k in filtered_fields, data.keys())
        }
    
    def validate_starttime(self, value):
        if value and value <= datetime.now(tz=timezone.utc):
            return value
        else:
            raise serializers.ValidationError('game cannot start in the future')

    def validate_endtime(self, value):
        if value and value <= datetime.now(tz=timezone.utc):
            return value
        else:
            raise serializers.ValidationError('game cannot end in the future')