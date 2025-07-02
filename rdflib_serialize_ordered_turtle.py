# rdflib_serialize_ordered_turtle.py
"""
Description: This script reads an ontology file in the repository and orders the contents in Turtle syntax for easier diff comparisons.

This is a GitHub version of the script to be used for GitHub Actions.

This process is handled first by using the RDFLib Python library to parse the ontology file.
    For code, see: https://github.com/RDFLib/rdflib
    For documentation: see: https://rdflib.readthedocs.org/

Then an extension to the RDFLib serializer is used to sort the order the URIs.  Documentation is not very good.
    For code/README, see: https://github.com/tgbugs/pyontutils/blob/master/ttlser/docs/ttlser.md
    For installation, see: https://pypi.org/project/ttlser/

Author: Christopher Weedall
Created: 2025-03-03
Modified: 2025-03-05
Modified: 2025-07-02
    Description:
        - Removed otsrdflib which appears to be unmaintained and is not sorting consistently (e.g. ordering of rdfs:subClassOf restrictions varies each time).
        - Identified embedded blank nodes (i.e. the blank node objects and which predicates they follow) and do several passes to replace those blanks nodes.
            - RDFLIB is a bit weird because it will correctly embed/inline blank nodes if the blank nodes are created via RDFLIB.
                However, if the blank node was created with a different tool/method (e.g. Protege), then RDFLIB keeps the blank node reference as-is.
                Despite this process seeming somewhat inefficient, it seems to be the only way to fix GitHub diff-ing for readability.
        - Replaced otsrdflib with ttlser's CustomTurtleSerializer which is seems to be actively maintained as of early 2025.
            - It is a deterministic Turtle serializer.
Created: 2025-03-03
Modified: 2025-03-05
License: GNU General Public License (GPL) v3.0
Copyright: 2025 © Christopher Weedall
"""

import argparse
import os
import pathlib
import re
import sys

import git

from rdflib import BNode, Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS, XSD

from ttlser import CustomTurtleSerializer

# Initialize parser
parser = argparse.ArgumentParser(description = "Ordered serializer for an existing Ontology file")
parser.add_argument('input_filename', help='The name of the input ontology file')
args = parser.parse_args()

input_filename = args.input_filename

ExitCode = 0

print(f"-- START: create ordered Turtle ontology file --")

WORKSPACE = git.Repo('.', search_parent_directories=True).working_dir
GITHUB_RUN_NUMBER = os.getenv('GITHUB_RUN_NUMBER')

## Turtle file extension
turtleFileExtension = '.ttl'

## Base filename for the ontology
baseOntologyFilename = pathlib.Path(input_filename).stem

## Input Ontology filename and path
ontologyFilePath = pathlib.Path(input_filename)

## Output Ordered Turtle ontology filename and path
orderedOntologyFilename = baseOntologyFilename + '_ordered_turtle' + turtleFileExtension
orderedOntologyFilePath = f"{WORKSPACE}/{orderedOntologyFilename}"

## NEED THIS FOR THE LOCAL SCRIPT (BUT NOT FOR THE GITHUB VERSION)
def normalize_line_endings(text):
  return text.replace('\r\n', '\n').replace('\r', '\n')

def rename_blank_nodes_to_fix_generated_names(graph, allowed_predicates=[]):
    newgraph = graph
    
    if type(allowed_predicates) is list:
        for predicate in allowed_predicates:
            if type(predicate) is list:
                newgraph = replace_blank_nodes_based_on_predicate_type(newgraph, allowed_predicates=predicate)
            else:
                newgraph = replace_blank_nodes_based_on_predicate_type(newgraph, allowed_predicates=[predicate])
    
    return newgraph
    
def replace_blank_nodes_based_on_predicate_type(graph, allowed_predicates=[]):
    newgraph = graph
    
    if type(allowed_predicates) is list:
        add_new = {}
        
        for orig_subj, orig_pred, orig_obj in newgraph:   
            if isinstance(orig_obj, BNode) and orig_pred in allowed_predicates:
                new_triples = set()
                
                for p, o in newgraph.predicate_objects(subject=orig_obj):
                    new_triples.add((None, p, o))
                
                ## == BEGIN BLANK NODE CREATION/NAMING ================================================================================
                # Should always be owl:Restriction(?)
                blank_node_type_objects = list(newgraph.objects(subject=orig_obj, predicate=RDF.type))
                blank_node_type = ('_' + blank_node_type_objects[0]) if blank_node_type_objects else ''
                blank_node_onProperty_objects = list(newgraph.objects(subject=orig_obj, predicate=OWL.onProperty))
                blank_node_onProperty_name = ('_' + blank_node_onProperty_objects[0]) if blank_node_onProperty_objects else ''
                
                blank_node_restriction_type_name = ''
                for p, o in newgraph.predicate_objects(subject=orig_obj):
                    if p in [OWL.qualifiedCardinality, OWL.minQualifiedCardinality, OWL.maxQualifiedCardinality]:
                        blank_node_restriction_type_name = p.fragment
                        break

                ## Get restriction(?) details to set blank node name
                blank_node_naming_details = blank_node_type + blank_node_onProperty_name + blank_node_restriction_type_name
                
                #bn = BNode('!!@@=====@@!!')
                bn = BNode()
                if orig_pred == RDFS.subClassOf:
                    bn = BNode(orig_subj + orig_pred + blank_node_naming_details)
                elif orig_pred == OWL.annotatedTarget:
                    orig_node_type_objects = list(newgraph.objects(subject=orig_subj, predicate=RDF.type))
                    orig_node_type_name = ('_' + orig_node_type_objects[0]) if orig_node_type_objects else ''
                    orig_node_annotatedSource_objects = list(newgraph.objects(subject=orig_subj, predicate=OWL.annotatedSource))
                    orig_node_annotatedSource_name = ('_' + orig_node_annotatedSource_objects[0]) if orig_node_annotatedSource_objects else ''
                    bn = BNode(orig_node_type_name + orig_node_annotatedSource_name  + orig_pred + blank_node_naming_details)
                ## == END BLANK NODE CREATION/NAMING ================================================================================
                
                for triple in new_triples:
                    s, p, o = triple
                    add_new.setdefault(orig_obj, []).append((bn, p, o))
                
                add_new.setdefault(orig_obj, []).append((orig_subj, orig_pred, bn))
                    
        for key in add_new:
            ## First remove all the old blank node references
            newgraph.remove((None, None, key))
            newgraph.remove((key, None, None))
            
            ## Then add all the newly created triples to replace them
            for triple in add_new[key]:
                newgraph.add(triple)
    
    return newgraph

## Create graph object from RDFLib to parse the ontology .ttl file.
graph = Graph()

try:
    ## Read the ontology file.
    print(f"Reading input ontology file")

    ## Need to read file and normalize line endings (Windows/Linux issue)
    with open(f"{ontologyFilePath}", 'r', encoding='utf-8') as file:
       file_content = file.read()
    file_content = normalize_line_endings(file_content)
except Exception as e:
    print(f"::error ::Failed to read input ontology file")
    print(e)
    ExitCode = 1

try:
    ## Parse the ontology file contents into an RDFLIB Graph
    print(f"Parsing input ontology file")
    
    ## Specify the format based on the filename/file extension
    graph.parse(data=file_content, format=f'{guess_format(input_filename)}')
    
except Exception as e:
    try:
        ## Sometimes, such as .owl files, the format can be Turtle, instead of what RDFLIB guesses the format should be
        graph.parse(data=file_content, format='turtle')
    except Exception as e:
        print(f"::error ::Failed to parse input ontology file")
        print(e)
        ExitCode = 1

## Bind the namespaces
ontology_namespace = ''
for prefix, namespace_uri in graph.namespace_manager.namespaces():
    if prefix == '':
        ontology_namespace = namespace_uri

graph.bind('', ontology_namespace)
graph.bind('rdf', RDF)
graph.bind('rdfs', RDFS)
graph.bind('owl', OWL)
graph.bind('xsd', XSD)

try:
    ## Remove all blank nodes from the parsed ontology.
    ## These blank nodes always have randomly generated ID labels which differ each time.
    print(f"Removing/renaming blank nodes")
    
    ## The order of these predicts is sorted by "deepness" and should not be altered.
    predicates_for_obj_bnodes = [RDFS.domain, RDFS.range, OWL.withRestrictions, OWL.onDataRange,  OWL.annotatedTarget, OWL.onDataRange, RDFS.subClassOf]
    
    ## Create new graph from original graph where the blank nodes are in-line OR named better.
    newgraph = rename_blank_nodes_to_fix_generated_names(graph, allowed_predicates=predicates_for_obj_bnodes)
            
    ## Avoid the junky "ns1" prefix renaming that RDFLIB does.
    newgraph.bind('', ontology_namespace, override=True, replace=True)

    ## Use the extenion to order the graph data.
    print(f"Creating serializing for ordered Turtle")
    serializer = CustomTurtleSerializer(newgraph)
    #serializer = CustomTurtleSerializer(graph)

except Exception as e:
    print(f"::error ::Failed to remove/rename blank nodes")
    print(e)
    ExitCode = 1
    
try:
    ## Output the ordered ontology in Turtle syntax.
    print(f"Writing serialized ontology with ordered Turtle")
    with open(f"{orderedOntologyFilePath}", 'wb') as fp:
        serializer.serialize(fp)
    
except Exception as e:
    print(f"::error ::Failed to create ordered Turtle file")
    print(e)
    ExitCode = 1

print(f"-- END: create ordered Turtle ontology file --")

sys.exit(ExitCode)
