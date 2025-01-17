import requests
import logging
import zipfile
import re
import io

logger = logging.getLogger(__name__)


class Api():
    """Class to serve as an abstraction layer to interact with the GitHub API.
    It handles utilizing proxies, along with passing the PAT and handling any
    rate limiting or network issues.
    """

    GITHUB_URL = "https://api.github.com"
    RUNNER_RE = re.compile(r'Runner name: \'([\w+-]+)\'')
    MACHINE_RE = re.compile(r'Machine name: \'([\w+-]+)\'')

    def __init__(self, pat: str, version: str = "2022-11-28",
                 http_proxy: str = None, socks_proxy: str = None):
        """Initialize the API abstraction layer to interact with the GitHub
        REST API.

        Args:
            pat (str): GitHub personal access token that will be used for API
            calls.
            version (str): API version to use that will be passed with the
            X-GitHub-Api-Version header.
            http_proxy (str, optional): HTTP Proxy to use for API calls.
            Defaults to None.
            socks_proxy (str, optional): SOCKS Proxy to use for API calls.
            Defaults to None.
        """
        self.pat = pat
        self.proxies = None
        self.verify_ssl = True
        self.headers = {
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {pat}',
            'X-GitHub-Api-Version': version
        }

        if http_proxy and socks_proxy:
            raise ValueError('A SOCKS & HTTP proxy cannot be used at the same '
                             'time! Please pass only one!')

        if http_proxy:
            # We are likely using BURP, so disable SSL.
            requests.packages.urllib3.disable_warnings()
            self.verify_ssl = False
            self.proxies = {
                'http': f'http://{http_proxy}',
                'https': f'http://{http_proxy}'
            }
        elif socks_proxy:
            self.proxies = {
                'http': f'socks5://{socks_proxy}',
                'https': f'socks5://{socks_proxy}'
            }

    def __process_run_log(self, log_content: bytes, run_info: dict):
        """Utility method to process a run log zip file.

        Args:
            log_content (bytes): Zip file downloaded from GitHub
            run_info (dict): Metadata about the run from the GitHub API
        Returns:
            dict: metadata about the run execution.
        """
        with zipfile.ZipFile(io.BytesIO(log_content)) as runres:

            for zipinfo in runres.infolist():
                if "Set up job" in zipinfo.filename:
                    with runres.open(zipinfo) as run_setup:
                        content = run_setup.read().decode()
                        if "Runner name" in content or \
                                "Machine name" in content:

                            # Need to replace windows style line
                            # return with linux..
                            matches = Api.RUNNER_RE.search(content)
                            runner_name = matches.group(1) if matches else None

                            matches = Api.MACHINE_RE.search(content)
                            hostname = matches.group(1) if matches else None

                            log_package = {
                                "setup_log": content,
                                "runner_name": runner_name,
                                "machine_name": hostname,
                                "run_id": run_info["id"],
                                "run_attempt": run_info["run_attempt"]
                            }
                            return log_package

    def call_get(self, url: str, params: dict = None):
        """Internal method to wrap a GET request so that proxies and headers
        do not need to be repeated.

        Args:
            url (str): Url path for the API request
            params (dict, optional): Parameters to pass to the request.
            Defaults to None.

        Returns:
            Response: Returns the requests response object.
        """
        request_url = Api.GITHUB_URL + url

        logger.debug(f'Making GET API request to {request_url}!')
        api_response = requests.get(request_url, headers=self.headers,
                                    proxies=self.proxies, params=params,
                                    verify=self.verify_ssl)
        logger.debug(
            f'The GET request to {request_url} returned a'
            f' {api_response.status_code}!')

        return api_response

    def call_post(self, url: str, params: dict = None):
        """Internal method to wrap a POST request so that proxies and headers
        do not need to be updated in each method.

        Args:
            url (str): URL path to make POST request to.
            params (dict, optional): Parameters to send as part of the request.
            Defaults to None.
        Returns:
            Response: Returns the requests response object.
        """
        request_url = Api.GITHUB_URL + url
        logger.debug(f'Making POST API request to {request_url}!')

        api_response = requests.post(request_url, headers=self.headers,
                                     proxies=self.proxies, json=params,
                                     verify=self.verify_ssl)
        logger.debug(
            f'The POST request to {request_url} returned a '
            f'{api_response.status_code}!')

        return api_response

    def call_delete(self, url: str, params: dict = None):
        """Internal method to wrap a POST request so that proxies and headers
        do not need to be updated in each method.

        Args:
            url (str): URL path to make POST request to.
            params (dict, optional): Parameters to send as part of the request.
            Defaults to None.
        Returns:
            Response: Returns the requests response object.
        """
        request_url = Api.GITHUB_URL + url
        logger.debug(f'Making DELETE API request to {request_url}!')

        api_response = requests.delete(request_url, headers=self.headers,
                                       proxies=self.proxies, json=params,
                                       verify=self.verify_ssl)
        logger.debug(
            f'The POST request to {request_url} returned a '
            f'{api_response.status_code}!')

        return api_response

    def delete_repository(self, repo_name: str):
        """Deletes the provided repository, if the user has administrative
        permissions on that repository.

        Args:
            repo_name (str): Name of repository to delete in Org/Owner format.
        Returns:
            bool: True if the repository was deleted, False otherwise.
        """
        result = self.call_delete(f"/repos/{repo_name}")

        if result.status_code == 204:
            logger.info(f"Successfully deleted {repo_name}!")
        else:
            logger.warning(f"Unable to delete repository {repo_name}!")
            return False

        return True

    def fork_repository(self, repo_name: str):
        """Creates a fork of a public repository and returns the name of
        the newly created fork.

        Args:
            repo_name (str): Name of the repository to fork.

        Returns:
            str: Full name of the newly forked repo in User/Repo format. False
            if there was a faiure.
        """
        post_params = {
            "default_branch_only": True
        }

        result = self.call_post(
            f"/repos/{repo_name}/forks",
            params=post_params
        )

        if result.status_code == 202:
            fork_info = result.json()
            return fork_info['full_name']
        elif result.status_code == 403:
            # likely permission error, log it.
            logger.warning("Forking this repository is forbidden!")
            return False
        elif result.status_code == 404:
            logger.warning(
                "Unable to fork due to 404, ensure repository exists."
            )
            return False
        else:
            logger.warning("Repository fork failed!")
            return False

    def create_fork_pr(self, target_repo: str,
                       source_user: str, source_branch: str,
                       target_branch: str, pr_title: str):
        """Creates a pull request from source_repo to target_repo. This is

        Args:
            target_repo (str): Target repo  (the one we are targeting)
            source_repo (str): Source repo for the PR (the one we own)
        Returns:
            str: URL of the newly created pull-request.
        """
        pr_params = {
            "title": pr_title,
            "head": f"{source_user}:{source_branch}",
            "base": f"{target_branch}",
            "body": "This is a test pull request greated for CI/CD"
                    " vulnerability testing purposes.",
            "maintainer_can_modify": False,
            "draft": True
        }

        result = self.call_post(
            f"/repos/{target_repo}/pulls",
            params=pr_params
        )

        if result.status_code == 201:
            details = result.json()
            return details['html_url']
        else:
            logger.warning(
                f"Failed to create PR for fork,"
                f" the status code was: {result.status_code}!"
            )
            return None

    def check_organizations(self):
        """Check organizations that the authenticated user belongs to.

        Returns:
            list(str): List of strings containing the organization names that
            the user is a member of.
        """

        result = self.call_get('/user/orgs')

        if result.status_code == 200:

            organizations = result.json()

            return [org['login'] for org in organizations]
        elif result.status_code == 403:
            return []

    def get_repository(self, repository: str):
        """Retrieve a repository using the GitHub API.

        Args:
            repository (str): Repository name in org/Repo format.
        Returns:
            dict: Dictionary containing repository info from the GitHub API.
        """
        result = self.call_get(f'/repos/{repository}')

        if result.status_code == 200:
            return result.json()

    def get_organization_details(self, org: str):
        """Query the GitHub API for details about the specific organization.

        If the token has an org admin scope, then this will reveal additional
        information about the org.

        Args:
            org (str): Name of the GitHub organization.
        Returns:
            dict: Dictionary containing the organization's details from the
            GitHub API.
        """
        result = self.call_get(f'/orgs/{org}')

        if result.status_code == 200:
            org_info = result.json()

            return org_info

        elif result.status_code == 404:
            logger.info(f'The organization {org} was not found or there'
                        ' is a permission issue!')

    def validate_sso(self, org: str, repository: str):
        """Query a repository in the organization to determine if SSO has been
        enabled for this PAT.

        If the query returns a 403 and an error message of "Resource protected
        by organization SAML enforcement. You must grant your Personal Access
        token access to this organization." then the PAT does not have
        permissions to this organization.

        Args:
            repository (str): Repository name in org/Repo format.
        Returns:
            bool: True if the organization is accessible either because SSO is
            not enabled, or if the PAT has been validated with SSO to that
            organization.
        """
        org_repos = self.call_get(f'/orgs/{org}/repos')

        if org_repos.status_code != 200:
            logger.warning(
                    "SSO does not seem to be enabled for this PAT!"
                    " Error message:"
                    f" {org_repos.json()['message']}"
            )
            return False

        result = self.call_get(f"/repos/{repository}")
        if result.status_code == 403:
            logger.warning(
                    "SSO does not seem to be enabled for this PAT! However,"
                    "this PAT does have some access to the GitHub Enterprise. "
                    f"Error message: {result.json()['message']}"
            )
            return False
        else:
            return True

    def check_org_runners(self, org: str):
        """Checks runners associated with an organization.

        This requires a token with the `admin:org` scope.

        Args:
            org (str): Name of the organization

        Returns:
            dict: Dictionary containing information about the runners.
        """
        result = self.call_get(f'/orgs/{org}/actions/runners')

        if result.status_code == 200:

            runner_info = result.json()
            if runner_info['total_count'] > 0:
                return runner_info
        else:
            logger.warning(
                f"Unable to query runners for {org}! This is likely due to the"
                " PAT permission level!"
            )

    def check_org_repos(self, org: str, type: str):
        """Check repositories present within an organization.

        Args:
            org (str): Organization to check repositories for.
            private (bool, optional): Whether to only check private
            repositories. Defaults to True.

        Returns:
            list: List of dictionaries representing repositories within an
            organization.
        """

        if type not in ['all', 'public', 'private', 'forks', 'sources',
                        'member', 'internal']:
            raise ValueError("Unsupported type!")

        get_params = {
            "type": type,
            "per_page": 100,
            "page": 1
        }

        org_repos = self.call_get(f'/orgs/{org}/repos', params=get_params)

        repos = []
        if org_repos.status_code == 200:
            listing = org_repos.json()

            repos.extend(listing)
            # Check if there are more pages
            while len(listing) == 100:
                get_params['page'] += 1
                org_repos = self.call_get(
                    f'/orgs/{org}/repos', params=get_params)
                if org_repos.status_code == 200:
                    listing = org_repos.json()
                    repos.extend(listing)
        else:
            logger.info(f'[-] {org} requires SSO!')
            return None

        return repos

    def check_user(self):
        """Gets the authenticated user associated with a GitHub PAT and returns
        the username and available scopes.

        Format:

        {
            'user': username,
            'scopes': [ scope0, scope1, ...]
        }

        Returns:
            dict: User associated with the PAT, None otherwise.
        """
        result = self.call_get('/user')

        if result.status_code == 200:
            resp_headers = result.headers.get('x-oauth-scopes')
            if resp_headers:
                scopes = [scope.strip() for scope in resp_headers.split(',')]
            else:
                scopes = []

            user_scopes = {
                'user': result.json()['login'],
                'scopes': scopes,
                'name': result.json()['name']
            }

            return user_scopes
        else:
            logger.warning('Provided token was not valid or has expired!')

        return None

    def get_repo_branch(self, repo: str, branch: str):
        """Check whether a specific branch exists on a remote.

        Args:
            repo (str): Name of the repository to check.
            branch (str): Name of the branch to check.

        Returns:
            int: Returns 1 upon success, 0 if the branch was not found, and -1
            if there was a failure retrieving the branch.
        """
        res = self.call_get(f'/repos/{repo}/branches/{branch}')
        if res.status_code == 200:
            return 1
        elif res.status_code == 404:
            return 0
        else:
            logger.warning("Failed to check repo for branch! "
                           f"({res.status_code}")
            return -1

    def get_repo_runners(self, full_name: str):
        """Get self-hosted runners associated with the repository.

        Args:
            full_name (str): Name of the repository in Org/Repo format.

        Returns:
            list: List of self hosted runners from the repository.
        """
        logger.debug(f'Enumerating repo level runners within {full_name}')
        runners = self.call_get(f'/repos/{full_name}/actions/runners')

        if runners.status_code == 200:
            runner_list = runners.json()['runners']
            if len(runner_list) > 0:
                logger.debug(
                    f'Identified {len(runner_list)}'
                    ' runners in the repository!')

            return runner_list
        else:
            logger.debug(
                f'Did not identify repo-level runners for {full_name}!')

        return None

    def retrieve_run_logs(self, repo_name: str, short_circuit: str = True):
        """Retrieve the most recent run log associated with a repository.

        Args:
            repo_name (str): Full name of the repository.
            short_circuit (bool, optional): Whether to return as soon as the
            first instance of a self-hosted runner is detected. Defaults to
            True.

        Returns:
            list: List of run logs for runs that ran on self-hosted runners.
        """
        runs = self.call_get(f'/repos/{repo_name}/actions/runs')

        run_logs = []

        if runs.status_code == 200:
            logger.debug(f'Enumerating runs within {repo_name}')
            for run in runs.json()['workflow_runs']:
                run_log = self.call_get(
                    f'/repos/{repo_name}/actions/runs/{run["id"]}/'
                    f'attempts/{run["run_attempt"]}/logs')

                if run_log.status_code == 200:
                    run_log = self.__process_run_log(run_log.content, run)
                    if run_log:
                        run_logs.append(run_log)
                        if short_circuit:
                            return run_logs
                else:
                    logger.debug(
                        f"Call to retrieve run logs from {repo_name} run "
                        f"{run['id']} attempt {run['run_attempt']} returned "
                        f"{run_log.status_code}!")

        return run_logs

    def parse_workflow_runs(self, repo_name: str):
        """Returns the number of workflow runs associated with the repository.

        Args:
            repo_name (str): Name of the repository in Org/Repo format to parse
            workflow runs for.

        Returns:
            int: Number of workflow runs associated with the repository, None
            if there was a failure.
        """
        runs = self.call_get(f'/repos/{repo_name}/actions/runs')

        if runs.status_code == 200:

            return (runs.json()['total_count'])
        else:
            logger.warning('Unable to query workflow runs.')

        return None

    def get_recent_workflow(self, repo_name: str, sha: str):
        """Returns the id of the latest workflow from the provided user on the
        provided branch"

        Args:
            repo_name (str): Name of the repository to get a recent workflow
            from.
            sha (str): SHA of the commit that triggered the workflow.

        Returns:
            str: ID of the workflow if it exists, 0 otherwise. -1 is returned
            if a failure occurred querying the workflow.
        """

        req = self.call_get(f'/repos/{repo_name}/actions/runs?head_sha={sha}')

        if req.status_code != 200:
            logger.warning('Unable to query workflow runs.')
            return -1

        data = req.json()

        if data['total_count'] == 0:
            return 0
        return data['workflow_runs'][0]['id']

    def get_workflow_status(self, repo_name: str, workflow_id: int):
        """Returns the status if the workflow by id.

        Args:
            repo_name (str): Name of the repository that has the workflow.
            workflow_id (int): ID of the workflow.

        Returns:
            int: 1 if the workflow has completed, 0 if it is pending, and -1 if
            there was a failure.
        """
        req = self.call_get(f'/repos/{repo_name}/actions/runs/{workflow_id}')

        if req.status_code != 200:
            logger.warning('Unable to query the workflow.')
            return -1

        data = req.json()

        if data.get('status', 'queued') in ['queued', 'in_progress']:
            return 0
        return 1 if data.get('conclusion', 'failure') == 'success' else -1

    def delete_workflow_run(self, repo_name: str, workflow_id: int):
        """Deletes a previous workflow run.

        Args:
            repo_name (str): Name of the repository that has the workflow.
            workflow_id (int): ID of the workflow.

        Returns:
            bool: True if the workflow was deleted, false otherwise.
        """
        req = self.call_delete(f'/repos/{repo_name}/actions/runs/'
                               f'{workflow_id}')

        return req.status_code == 204

    def download_workflow_logs(self, repo_name: str, workflow_id: int):
        """Download worfklow run logs and saves them to a zip file under the
        workflow ID.

        Args:
            repo_name (str): Name of the repository that has the workflow.
            workflow_id (int): ID of the workflow.

        Returns:
            bool: True of the workflow log was downloaded, false otherwise.
        """
        req = self.call_get(f"/repos/{repo_name}/actions/runs/"
                            f"{workflow_id}/logs")

        if req.status_code != 200:
            return False

        with open(f"{workflow_id}.zip", "wb+") as f:
            f.write(req.content)
        return True
