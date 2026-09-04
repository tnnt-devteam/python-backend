from django import forms
import unicodedata

# Helper function for common checks on unvalidated user input strings
def text_field_clean(input_str, input_type, refuse_slashes=False):
    # refuse slashes, since this will mess up routing to /clan/<clanname>
    # endpoints
    # (post 2021 TODO: we could probably improve this by making the clan name
    # a GET parameter rather than part of the URL)
    if refuse_slashes and '/' in input_str:
        raise forms.ValidationError('%s cannot contain slashes' % input_type)

    # allow diacritics, but only one combining character per regular character
    # (otherwise ZALGO style clan names can be created which mess up other
    # parts of the page)
    prevcombine = False
    for char in input_str:
        nowcombine = unicodedata.combining(char)
        if nowcombine and prevcombine:
            raise forms.ValidationError(
                '%s cannot have more than one consecutive combining character' % input_type)
        prevcombine = nowcombine

    # don't allow non-printable characters
    if not input_str.isprintable():
        raise forms.ValidationError(
            '%s cannot contain non-printable characters' % input_type)

    # This started as a workaround for the database being utf8mb3, which can't
    # store 4-byte characters. The database has since been converted to
    # utf8mb4 (verified 2026-09-04), so the check is now a deliberate choice
    # to keep emoji and the like out of clan names and messages. If a certain
    # subset of 4-byte characters should be allowed, replace it with a more
    # narrowly scoped test.
    for char in input_str:
        if len(char.encode('utf-8')) >= 4:
            raise forms.ValidationError(
                ('%s cannot contain 4-byte UTF-8 characters (such as emoji)'
                 % input_type))

    return input_str

class CreateClanForm(forms.Form):
    clan_name = forms.CharField(max_length = 127, label='Create a clan:')

    # Custom validator for the clan_name field. Enforces some constraints we
    # don't want to allow in clan names.
    def clean_clan_name(self):
        data = self.cleaned_data['clan_name']
        return text_field_clean(data, "Clan names", True)

class InviteMemberForm(forms.Form):
    invitee = forms.CharField(max_length = 32, label='Invite:')

    def clean_invitee(self):
        data = self.cleaned_data['invitee']
        return text_field_clean(data, "Invitees")

class SetMessageForm(forms.Form):
    message = forms.CharField(max_length = 512, label='Update clan message:')

    def clean_message(self):
        data = self.cleaned_data['message']
        return text_field_clean(data, 'Clan messages')
