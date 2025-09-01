from rest_framework import serializers
from scoreboard.models import Player, Clan, Game, Achievement, Trophy


class TrophySerializer(serializers.ModelSerializer):
    class Meta:
        model = Trophy
        fields = ['name', 'description']


class AchievementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Achievement
        fields = ['name', 'description', 'ingameid']


class PlayerListSerializer(serializers.ModelSerializer):
    clan = serializers.SlugRelatedField(slug_field='name', read_only=True)
    ratio = serializers.ReadOnlyField()

    class Meta:
        model = Player
        fields = ['name', 'clan', 'wins', 'total_games', 'ratio']


class PlayerDetailSerializer(serializers.ModelSerializer):
    clan = serializers.SlugRelatedField(slug_field='name', read_only=True)
    trophies = TrophySerializer(many=True, read_only=True)
    ratio = serializers.ReadOnlyField()

    class Meta:
        model = Player
        fields = ['name', 'clan', 'wins', 'total_games', 'games_scummed',
                  'unique_deaths', 'unique_achievements', 'longest_streak',
                  'trophies', 'ratio', 'zscore']


class ClanSerializer(serializers.ModelSerializer):
    members = PlayerListSerializer(
        source='player_set', many=True, read_only=True
    )
    trophies = TrophySerializer(many=True, read_only=True)
    ratio = serializers.ReadOnlyField()

    class Meta:
        model = Clan
        fields = ['name', 'wins', 'total_games', 'ratio', 'members',
                  'trophies']


class GameSerializer(serializers.ModelSerializer):
    player = serializers.SlugRelatedField(
        slug_field='name', read_only=True
    )
    achievements = AchievementSerializer(many=True, read_only=True)

    class Meta:
        model = Game
        fields = ['player', 'role', 'race', 'gender', 'align', 'points',
                  'turns', 'death', 'endtime', 'won', 'achievements']
