import pytest

from pbg2sed2.classify import classify
from pbg2sed2.mapping import Options, translate
from pbg2sed2.reader import Document

pytest.importorskip("libsbml")

SBML = """<?xml version="1.0" encoding="UTF-8"?>
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core" level="3" version="1">
  <model id="m">
    <listOfCompartments><compartment id="c" size="{size}" constant="true" spatialDimensions="3"/></listOfCompartments>
    <listOfSpecies>
      <species id="A" compartment="c" initialConcentration="10" hasOnlySubstanceUnits="{hosu}" boundaryCondition="false" constant="false"/>
      <species id="B" compartment="c" initialConcentration="0" hasOnlySubstanceUnits="{hosu}" boundaryCondition="false" constant="false"/>
    </listOfSpecies>
    <listOfParameters>
      <parameter id="k" value="0.3" constant="true"/>
      <parameter id="g" value="1" constant="false"/>
    </listOfParameters>
    <listOfRules><assignmentRule variable="g"><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A</ci></apply></math></assignmentRule></listOfRules>
    <listOfReactions>
      <reaction id="R1" name="decay of A" reversible="false" fast="false">
        <listOfReactants><speciesReference species="A" stoichiometry="1" constant="true"/></listOfReactants>
        <listOfProducts><speciesReference species="B" stoichiometry="1" constant="true"/></listOfProducts>
        <kineticLaw><math xmlns="http://www.w3.org/1998/Math/MathML"><apply><times/><ci>k</ci><ci>A</ci>{extra}</apply></math></kineticLaw>
      </reaction>
    </listOfReactions>
  </model>
</sbml>
"""
TIME_FACTOR = '<csymbol encoding="text" definitionURL="http://www.sbml.org/sbml/symbols/time">t</csymbol>'


def model(tmp_path, size=1, hosu="false", extra=""):
    p = tmp_path / f"m_{size}_{hosu}_{abs(hash(extra))}.xml"
    p.write_text(SBML.format(size=size, hosu=hosu, extra=extra))
    return str(p)


def node(kind, cls, config, inputs=None, outputs=None, **extra):
    d = {"_type": kind, "address": f"local:{cls}", "config": config, "inputs": inputs or {}, "outputs": outputs or {}}
    d.update(extra)
    return d


def doc(sim, emitter_inputs, stores=None, header=None):
    state = {"sim": sim, "em": node("step", "RAMEmitter", {"emit": {}}, inputs=emitter_inputs)}
    state.update(stores or {})
    return Document(source="t", form="composite-file", state=state, header=header or {})


def run(d, **kw):
    return translate(d, classify(d), Options(name="t", **kw))


def utc_step(tmp_path, **cfg):
    c = {"model_source": model(tmp_path), "time": 10.0, "n_points": 11}
    c.update(cfg)
    return doc(node("step", "CopasiUTCStep", c, inputs={"species_counts": ["st", "counts"]}, outputs={"result": ["st", "result"]}),
               {"result": ["st", "result"]}, {"st": {"counts": {}, "result": {}}})


def test_utc_step_columns_are_species_and_non_constant_parameters(tmp_path):
    r = run(utc_step(tmp_path))
    assert r.status == "translatable", r.reasons
    s = r.sed2["tasks"]["s"]
    assert s["outputVariables"] == ["A", "B", "g"]
    assert s["independentVariableRange"] == {"_type": "numericRange", "start": 0.0, "end": 10.0, "numberOfSteps": 10}
    assert "relativeTolerance" not in s
    assert r.kind == "trajectory"


def test_start_time_and_tolerances(tmp_path):
    r = run(utc_step(tmp_path, start_time=2.0, time=3.0, n_points=4, relative_tolerance=1e-7, absolute_tolerance=1e-9))
    s = r.sed2["tasks"]["s"]
    assert s["independentVariableRange"]["start"] == 2.0 and s["independentVariableRange"]["end"] == 5.0
    assert s["relativeTolerance"] == 1e-7 and s["absoluteTolerance"] == 1e-9


@pytest.mark.parametrize("cfg,fragment", [
    ({"method": "stochastic"}, "method"),
    ({"selections": ["Time"]}, "selections"),
    ({"output_times": [1.0]}, "output_times"),
    ({"species_units": "amount"}, "amount"),
    ({"step_size": 0.1}, "step_size"),
    ({"model_source": "https://example.org/m.xml"}, "URL"),
    ({"model_source": "missing.xml"}, "not found"),
])
def test_copasi_refusals(tmp_path, cfg, fragment):
    r = run(utc_step(tmp_path, **cfg))
    assert r.status == "not-translatable" and fragment in " ".join(r.reasons)


def test_non_empty_input_store_is_refused(tmp_path):
    d = utc_step(tmp_path)
    d.state["st"]["counts"] = {"A": 5.0}
    r = run(d)
    assert r.status == "not-translatable" and "input stores" in r.reasons[0]


def test_copasi_document_is_not_read_as_sbml(tmp_path):
    p = tmp_path / "m.cps"
    p.write_text("<?xml version='1.0'?><COPASI versionMajor='4'></COPASI>")
    r = run(utc_step(tmp_path, model_source=str(p)))
    assert "not an SBML file" in r.reasons[0]


def test_amount_and_concentration_agree_only_for_unit_volumes(tmp_path):
    assert run(utc_step(tmp_path, model_source=model(tmp_path, hosu="true"))).status == "translatable"
    r = run(utc_step(tmp_path, model_source=model(tmp_path, size=2, hosu="true")))
    assert r.status == "not-translatable" and "hasOnlySubstanceUnits" in r.reasons[0]
    assert run(utc_step(tmp_path, model_source=model(tmp_path, size=2))).status == "translatable"


def test_steady_state_ids_and_flux_names(tmp_path):
    d = doc(node("step", "CopasiSteadyStateStep", {"model_source": model(tmp_path)}, outputs={"results": ["st", "r"]}),
            {"results": ["st", "r"]}, {"st": {"r": {}}})
    r = run(d)
    assert r.status == "translatable", r.reasons
    assert r.sed2["tasks"]["s"] == {"_type": "steadyState", "model": "#tasks:m.model", "outputVariables": ["A", "B", "R1"]}
    assert r.labels == {"decay of A": "R1"} and r.kind == "steady-state"


def test_steady_state_options_are_refused(tmp_path):
    d = doc(node("step", "CopasiSteadyStateStep", {"model_source": model(tmp_path), "criterion": "Distance"}, outputs={"results": ["st", "r"]}),
            {"results": ["st", "r"]}, {"st": {"r": {}}})
    assert "criterion" in run(d).reasons[0]


def process(tmp_path, extra="", **cfg):
    c = {"model_source": model(tmp_path, extra=extra), "time": 1.0, "intervals": 10}
    c.update(cfg)
    return doc(node("process", "CopasiUTCProcess", c, inputs={"species_concentrations": ["st", "c"], "species_counts": ["st", "n"]},
                    outputs={"species_concentrations": ["st", "c"], "fluxes": ["st", "f"], "time": ["st", "t"]}, interval=1.0),
               {"species_concentrations": ["st", "c"], "fluxes": ["st", "f"]}, {"st": {"c": {}, "n": {}, "f": {}, "t": []}})


def test_process_ticks_and_labels(tmp_path):
    r = run(process(tmp_path), duration=3.0)
    assert r.status == "translatable", r.reasons
    assert r.sed2["constants"] == {"duration": 3}
    assert r.sed2["tasks"]["s"]["independentVariableRange"]["interval"] == 1.0
    assert r.sed2["tasks"]["s"]["outputVariables"] == ["A", "B", "R1"]
    assert r.tick == 1.0 and r.labels == {"decay of A": "R1"}


def test_process_whose_model_uses_time_is_refused(tmp_path):
    r = run(process(tmp_path, extra=TIME_FACTOR), duration=3.0)
    assert r.status == "not-translatable" and "time" in r.reasons[0]
