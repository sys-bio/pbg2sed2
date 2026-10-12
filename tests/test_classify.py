from pbg2sed2.classify import class_name, classify, iter_nodes
from pbg2sed2.reader import Document


def node(kind, cls, inputs=None, outputs=None, **extra):
    d = {"_type": kind, "address": f"local:{cls}", "config": {}, "inputs": inputs or {}, "outputs": outputs or {}}
    d.update(extra)
    return d


def doc(state, **kw):
    return Document(source="t", form="composite-file", state=state, **kw)


def test_class_name_forms():
    assert class_name("local:Foo") == "Foo"
    assert class_name("local:!pkg.mod.Foo") == "Foo"
    assert class_name("") == "(no address)"


def test_tier_a_one_known_simulator_with_emitter():
    d = doc({"sim": node("step", "TelluriumUTCStep", outputs={"r": ["res"]}), "res": {},
             "em": node("step", "RAMEmitter", inputs={"r": ["res"]})})
    c = classify(d)
    assert c.tier == "A" and not c.opaque_classes


def test_tier_b_declarative_math_only():
    d = doc({"m": node("step", "MathExpressionStep", outputs={"y": ["y"]}), "y": 0.0})
    assert classify(d).tier == "B"


def test_tier_d_two_simulators_sharing_a_store():
    d = doc({"a": node("process", "TelluriumProcess", outputs={"s": ["x"]}, interval=1.0),
             "b": node("process", "CopasiUTCProcess", inputs={"s": ["x"]}, outputs={"s": ["x"]}, interval=1.0), "x": {}})
    c = classify(d)
    assert c.tier == "D" and c.coupled


def test_tier_e_single_opaque_process_and_d_when_coupled():
    assert classify(doc({"p": node("process", "MyThing", outputs={"o": ["x"]}), "x": 0})).tier == "E"
    d = doc({"p": node("process", "MyThing", outputs={"o": ["x"]}), "q": node("process", "YourThing", inputs={"i": ["x"]}), "x": 0})
    assert classify(d).tier == "D"


def test_coupled_model_class_is_tier_d():
    assert classify(doc({"p": node("process", "DynamicFBA")})).tier == "D"


def test_drawing_only_is_not_a_document_to_simulate():
    c = classify(doc({"p": node("process", "BigraphLink")}))
    assert c.tier == "none" and "drawing" in c.reasons[0]


def test_forward_translator_classes_are_tier_c():
    assert classify(doc({"t": node("step", "SedOdeSimulation")})).tier == "C"


def test_template_and_fragment_and_empty():
    assert classify(doc({"a": 1}, is_template=True)).tier == "template"
    assert classify(doc({"a": 1}, fragment=True)).tier == "fragment"
    assert classify(doc({"a": 1})).tier == "none"


def test_nested_composite_nodes_are_found():
    inner = {"x": node("process", "TelluriumProcess")}
    d = doc({"c": node("process", "Composite", config={"state": inner})})
    nodes = list(iter_nodes(d.state))
    assert [n.nested for n in nodes] == [False, True]
