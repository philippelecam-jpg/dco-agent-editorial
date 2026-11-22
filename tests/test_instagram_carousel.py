import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from PIL import Image
import pytest

import instagram_carousel as carousel


def package():
    return {'slides': [{'titre': 'Une règle claire pour vos achats',
                        'texte': 'Définissez les seuils et les exceptions avant de déléguer une commande.'}] * 7,
            'legende': 'Des règles explicites pour votre PME.'}


def test_render_seven_portrait_slides():
    with TemporaryDirectory() as directory:
        folder = Path(directory)
        carousel.render(carousel.validate(package()), folder)
        assert len(list(folder.glob('*.jpg'))) == 7
        assert Image.open(folder / '1.jpg').size == (1080, 1350)


def test_reject_overlong_text():
    data = package()
    data['slides'][0]['texte'] = 'a' * 331
    with pytest.raises(ValueError):
        carousel.validate(data)


def test_uncertain_publication_is_not_repeated():
    client = Mock()
    client.find_published.return_value = None
    client.status.return_value = 'FINISHED'
    entry = {'caption': 'texte', 'container_id': '123', 'publication_demandee': True}
    with pytest.raises(carousel.MetaError):
        carousel.publish(client, entry, Path('unused'), [], checkpoint=Mock())
    client.publish.assert_not_called()


def test_recover_confirmed_publication():
    client = Mock()
    client.find_published.return_value = '456'
    client.request.return_value = {'media_type': 'CAROUSEL_ALBUM',
        'permalink': 'https://www.instagram.com/p/example/', 'children': {'data': [{}] * 7}}
    with TemporaryDirectory() as directory:
        path = Path(directory) / 'journal.json'
        carousel.publish(client, {'caption': 'texte'}, path, [], checkpoint=Mock())
        assert json.loads(path.read_text())['statut'] == 'publie'
    client.publish.assert_not_called()


def test_remote_checkpoint_failure_prevents_publication():
    client = Mock()
    client.find_published.return_value = None
    client.status.return_value = 'FINISHED'
    with TemporaryDirectory() as directory:
        with pytest.raises(RuntimeError):
            carousel.publish(client, {'caption': 'texte', 'container_id': '123'},
                             Path(directory) / 'journal.json', [],
                             checkpoint=Mock(side_effect=RuntimeError('push failed')))
    client.publish.assert_not_called()
