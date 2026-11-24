import pytest
from core.domain.producers import resolve_producer, KNOWN_PRODUCERS


def test_resolve_producer_millimages():
    assert resolve_producer(title="Molang - S1 Ep 1", series_name="Molang", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Моланг - Эпизод 10", series_name="Моланг", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Louie, mal mir ein Haus", series_name="Louie draw me !", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Luluś Ep 3", series_name="Luluś", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Didou dessine un arbre", series_name="Didou", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Mouk der Weltreisebär", series_name="Mouk", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Mokon suuri maailma", series_name="Mokon suuri maailma", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Diego & Ziggy Ep 4", series_name="Diego et Ziggy", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="La calle del Zoológico 64", series_name="64 Zoo Lane", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="動物園通り64番地", series_name="動物園通り64番地", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Kung Fu Bunny - Ep 1", series_name="Kung Fu Bunny", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Niko le petit renne 2", series_name="Niko", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Piccolo, Saxo & Cie", series_name="Piccolo Saxo", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Courte vidéo: Lascars", series_name="Lascars", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Pirata et Capitano", series_name="Pirata et Capitano", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Jump around [dt./OV]", series_name="Jump around", ip_name="UNMATCHED") == "Millimages"
    assert resolve_producer(title="Renaissance", series_name="Renaissance", ip_name="UNMATCHED") == "Millimages"


def test_resolve_producer_sunnyside():
    assert resolve_producer(title="Groovy el Marciano y el reciclaje", series_name="Groovy The Martian", ip_name="UNMATCHED") == "Sunnyside Studios"
    assert resolve_producer(title="Groovy Le Martien", series_name="Groovy", ip_name="UNMATCHED") == "Sunnyside Studios"
    assert resolve_producer(title="Superzoo - El rescate del río", series_name="Superzoo", ip_name="UNMATCHED") == "Sunnyside Studios"


def test_resolve_producer_externals():
    assert resolve_producer(title="Cool City Ep 1", series_name="Cool City", ip_name="UNMATCHED") == "Shadow Studio"
    assert resolve_producer(title="As Aventuras do Penguim Jasper", series_name="Jasper", ip_name="UNMATCHED") == "Shout! Factory"
    assert resolve_producer(title="Kit ^N^ Kate Ep 1", series_name="Kit N Kate", ip_name="UNMATCHED") == "Toonbox"


def test_resolve_producer_amuse():
    # Canonical matched IPs
    assert resolve_producer(title="The Crane", series_name="TOM_THE_TOW_TRUCK", ip_name="CAR_CITY") == "Amuse Animation"
    assert resolve_producer(title="Ep 1", series_name="SHARK_ACADEMY", ip_name="SHARK_ACADEMY") == "Amuse Animation"
    assert resolve_producer(title="Ep 2", series_name="DINO_CARTOONS", ip_name="DINO") == "Amuse Animation"
    
    # Confirmed Amuse series from UNMATCHED
    assert resolve_producer(title="Amber l'Ambulance", series_name="Amber l'Ambulance", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Aprende con Ethan la Volqueta", series_name="Ethan", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Bebes en Auto City", series_name="Bebes en Auto City", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Go Go Babies in Car City", series_name="Go Go Babies", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="El Taller de Pintura de Tom la Grúa", series_name="Tom's Paint Shop", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Aladdin & the genies' - Ep 1", series_name="Aladdin & the genies'", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="BIRDIE Ep 1", series_name="BIRDIE", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Lily's Lovely Songs - Nursery Rhymes for Kids", series_name="Lily's Lovely Songs", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="учимся вместе с Игорем", series_name="учимся вместе с Игорем", ip_name="UNMATCHED") == "Amuse Animation"
    
    # Extended Amuse Network Franchises
    assert resolve_producer(title="Baby Shark Song and Cartoon", series_name="Baby Shark", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Cam & Sam - Kids Songs", series_name="Cam & Sam", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="KidsFlix - Cartoons for Children", series_name="KidsFlix", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="One Zeez - Episode 1", series_name="One Zeez", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Pete the Ghost", series_name="Pete", ip_name="UNMATCHED") == "Amuse Animation"
    assert resolve_producer(title="Coloring Pages for Kids", series_name="Coloring", ip_name="UNMATCHED") == "Amuse Animation"

    # YouTube platform: Amuse CMS owned channels default to Amuse Animation
    assert resolve_producer(title="Random Promo Video", series_name="Unknown Series", ip_name="Unknown IP", platform="youtube") == "Amuse Animation"
    # Third-party titles distributed on YouTube still resolve to their external producer
    assert resolve_producer(title="Molang Episode 5", series_name="Molang", ip_name="Unknown IP", platform="youtube") == "Millimages"
    assert resolve_producer(title="Groovy The Martian", series_name="Groovy", ip_name="Unknown IP", platform="youtube") == "Sunnyside Studios"


def test_resolve_producer_unassigned():
    assert resolve_producer(title="Unknown Random Movie 1234", series_name="Unknown Series", ip_name="UNMATCHED") == "Sin Asignar"
    assert resolve_producer(title="", series_name="", ip_name="") == "Sin Asignar"
    assert resolve_producer(None, None, None) == "Sin Asignar"


def test_known_producers_list():
    assert "Amuse Animation" in KNOWN_PRODUCERS
    assert "Millimages" in KNOWN_PRODUCERS
    assert "Sunnyside Studios" in KNOWN_PRODUCERS
    assert "Shadow Studio" in KNOWN_PRODUCERS
    assert "Shout! Factory" in KNOWN_PRODUCERS
    assert "Toonbox" in KNOWN_PRODUCERS
    assert "Sin Asignar" in KNOWN_PRODUCERS
