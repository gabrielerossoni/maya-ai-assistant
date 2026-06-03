import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.news_tool import strip_tags


def test_strip_tags_decodes_html_entities():
    assert strip_tags("L&#39;Ue concede &quot;fondi&quot;") == 'L\'Ue concede "fondi"'


def test_strip_tags_removes_markup_before_display():
    assert strip_tags("<p>Notizia <strong>importante</strong></p>") == "Notizia importante"
