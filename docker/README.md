# Docker

This folder contains Docker build procedures for various aspects of MIRA.

## MIRA Front-end

This folder implements a Docker build procedure for building a neo4j instance
of MIRA's domain knowledge graph from a given node and edge dump. The node
and edge dumps are pulled from S3.

```shell
docker build --tag mira_dkg:latest .
```

If you want to test with local files, put `nodes.tsv.gz` and `edges.tsv.gz` in
this folder and use:

```shell
# Get graph data
cp ~/.data/mira/demo/import/nodes.tsv.gz nodes.tsv.gz
cp ~/.data/mira/demo/import/edges.tsv.gz edges.tsv.gz

# Build docker
docker build --file Dockerfile.local --tag mira_dkg:latest .
```

Once the build finished, you can run the container locally as

```shell
docker run -d -p 8771:8771 -e MIRA_NEO4J_URL=bolt://0.0.0.0:7687 --name mira_dkg mira_dkg:latest
```

This exposes a REST API at `http://localhost:8771`. Note that the `-d` flag
runs the container in the background. If you want to expose Neo4j's bolt port, also
add `-p 7687:7687`.

## MIRA Metaregistry

You can build the metaregistry with:

```shell
docker build --file Dockerfile.metaregistry --tag mira_metaregistry:latest .
```

Once the build finished, you can run the container locally as:

```shell
docker run --detach -p 8772:8772 --name mira_metaregistry mira_metaregistry:latest
```
