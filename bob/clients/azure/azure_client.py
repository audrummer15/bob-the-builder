import os
import json
import time

from azure.devops.credentials import BasicAuthentication
from azure.devops.connection import Connection
from azure.devops.v5_1.build.models import AgentSpecification, Build

from bob_build import BobBuild
from .azure_blueprint_factory import AzureBlueprintFactory
from .azure_blueprint import AzureBlueprint

class AzureClient:

    def __init__(self, config):
        self._credentials = BasicAuthentication('', config['azure_personal_access_token'])
        self._connection = Connection(base_url=config['azure_organization_url'], creds=self._credentials)


    def create_blueprint(self):
        return AzureBlueprintFactory(self._connection).create_blueprint()


    def load_blueprints(self, filename):
        return AzureBlueprint.load_from_file(filename)


    def save_blueprints(self, blueprints, filename):
        AzureBlueprint.save_blueprints_to_file(blueprints, filename)


    def build_blueprint(self, blueprint):
        bob_builds = []

        project = self.get_project_by_name(blueprint.get_project())
        definition = self.get_definition_by_name(project.name, blueprint.get_definition())
        queue = self.get_agent_queue_by_name(project.name, blueprint.get_agent_queue())
        if blueprint.get_agent_specification() != None:
            agent_specification = AgentSpecification(identifier=blueprint.get_agent_specification())
        else:
            agent_specification = None

        for instance in blueprint.get_build_instances():
            name = instance.get_name()
            parameters = json.dumps(instance.get_queue_time_variables())
            tags = instance.get_tags()
            if name is not None:
                print("\nStarting build for {}".format(name))

            build = self._build_definition(project, definition, queue, agent_specification, blueprint.get_source_branch(), parameters, tags)
            bob_build = BobBuild(name=name, original_build=build)
            if build.result == "succeeded":
                bob_build.result = BobBuild.STATUS_SUCCESS
                bob_build.download_urls = self._get_build_artifact_download_links(build)
            else:
                bob_build.result = BobBuild.STATUS_FAILURE

            bob_builds.append(bob_build)

        return bob_builds


    def download_build_artifacts(self, azure_build, download_dir='.', name=None):
        build_client = self._connection.clients.get_build_client()
        artifacts = build_client.get_artifacts(azure_build.project.name, azure_build.id)
        for artifact in artifacts:
            extension = self._get_extension_from_download_url(artifact.resource.download_url)
            if extension == None:
                extension = "zip"

            filename = "{}_{}.{}".format(artifact.name, azure_build.id, extension)
            if name is not None:
                filename = "{}_{}".format(name, filename)

            if not os.path.exists(download_dir):
                os.makedirs(download_dir)

            filepath = os.path.join(download_dir, filename)
            print ("Downloading {} ...".format(filepath), end='', flush=True)

            with open(filepath, 'wb') as f:
                for chunk in build_client.get_artifact_content_zip(azure_build.project.name, azure_build.id, artifact.name):
                    f.write(chunk)

            print(" Finished!")


    def _build_definition(self, project, definition, queue, agent_specification, source_branch, parameters, tags):
        build_client = self._connection.clients.get_build_client()
        new_build = Build(definition=definition, queue=queue, agent_specification=agent_specification, source_branch=source_branch, parameters=parameters)
        build = build_client.queue_build(new_build, project.id)

        previous_status = None
        while build.status != "completed":
            if previous_status != build.status:
                print("\nStatus - {}".format(build.status), end='')
                previous_status = build.status
            else:
                print(".", end='', flush=True)
            build = build_client.get_build(project.id, build.id)
            time.sleep(2)

        print()
        build_client.add_build_tags(tags, project.id, build.id)

        return build


    def _get_extension_from_download_url(self, url):
        extension = None
        format_split = url.split("format=")
        if len(format_split) > 0:
            extension = format_split[1].split("&")[0]
        return extension


    def _get_build_artifact_download_links(self, build):
        links = []
        build_client = self._connection.clients.get_build_client()
        artifacts = build_client.get_artifacts(build.project.name, build.id)
        for artifact in artifacts:
            links.append(artifact.resource.download_url)
        return links


    def get_project_by_name(self, project_name):
        core_client = self._connection.clients.get_core_client()
        return core_client.get_project(project_name)


    def get_definition_by_name(self, project_name, definition_name):
        build_client = self._connection.clients_v5_1.get_build_client()
        definitions = build_client.get_definitions(project_name, name=definition_name, include_all_properties=True)
        if len(definitions) > 1:
            print("Duplicate definitions exist for {}".format(definition_name))
            sys.exit(0)
        elif len(definitions) == 0:
            print("No definitions exist for {}".format(definition_name))
            sys.exit(0)
        return definitions[0]


    def get_agent_queue_by_name(self, project_name, queue_name):
        task_agent_client = self._connection.clients_v5_1.get_task_agent_client()
        queues = task_agent_client.get_agent_queues(project_name, queue_name=queue_name)
        if len(queues) > 1:
            print("Duplicate queues exist for {}".format(queue_name))
            sys.exit(0)
        elif len(queues) == 0:
            print("No queues exist for {}".format(queue_name))
            sys.exit(0)
        return queues[0]