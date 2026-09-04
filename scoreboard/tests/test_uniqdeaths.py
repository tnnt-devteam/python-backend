from django.test import SimpleTestCase
from tnnt.uniqdeaths import normalize, reject


class NormalizeTests(SimpleTestCase):

    def check(self, raw, expected):
        self.assertEqual(normalize(raw), expected)

    def test_invisible_named_unique_keeps_its_space(self):
        # used to produce "killed by theWizard of Yendor", a distinct (and
        # farmable) unique death from the visible one
        self.check('killed by the invisible Wizard of Yendor',
                   'killed by the Wizard of Yendor')

    def test_invisible_ordinary_monster(self):
        self.check('killed by an invisible stalker', 'killed by a stalker')
        self.check('killed by invisible gnome lords', 'killed by gnome lords')

    def test_article_and_while_clause(self):
        self.check('killed by an owlbear, while sleeping',
                   'killed by a owlbear')

    def test_shopkeeper_variants_collapse(self):
        self.check('killed by Mr. Asidonhopo; the shopkeeper',
                   'killed by a shopkeeper')
        self.check('killed by Ms. Izchak, the shopkeeper',
                   'killed by a shopkeeper')

    def test_named_monsters_and_remnants(self):
        self.check('killed by a kitten called Fluffy', 'killed by a kitten')
        self.check("killed by post163's ghost", 'killed by a ghost')
        self.check('killed by k2 the vampire', 'killed by a vampire')

    def test_priest_and_minion(self):
        self.check('killed by the high priestess of Anhur',
                   'killed by the high priest(ess) of a deity')
        self.check('killed by an Aleax of Anhur',
                   'killed by a minion of a deity')

    def test_gendered_pronouns(self):
        self.check('killed by touching his own artifact',
                   'killed by touching an artifact')
        self.check('choked on her food', 'choked on something')


class RejectTests(SimpleTestCase):

    def test_rejections(self):
        for death in ('ascended', 'quit', 'escaped',
                      'escaped (in celestial disgrace)'):
            self.assertTrue(reject(death), death)
        self.assertFalse(reject('killed by a newt'))
