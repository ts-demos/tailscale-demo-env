import pulumi_aws as aws
import pulumi_kubernetes as k8s
import pulumi_random as random
import pulumi_postgresql as postgresql
import pulumi

PROJECT_NAME = pulumi.get_project()
STACK = pulumi.get_stack()
PULUMI_CONFIG = pulumi.Config("pulumi")
PULUMI_ORG = PULUMI_CONFIG.require("orgName")
RESOURCE_PREFIX = PULUMI_CONFIG.require("resourcePrefix")
NAME = "poll"

TAGS = {
    "environment": STACK,
    "project": PROJECT_NAME,
    "owner": "lbriggs",
    "deployed_by": "pulumi",
    "org": "lbrlabs",
}

LABELS = TAGS


CLUSTER = pulumi.StackReference(f"{PULUMI_ORG}/lbr-demo-eks/{STACK}")
CLUSTER_NAME = CLUSTER.require_output("cluster_name")
KUBECONFIG = CLUSTER.require_output("kubeconfig")
VPC = pulumi.StackReference(f"{PULUMI_ORG}/lbr-demo-vpcs/{STACK}")
VPC_ID = VPC.get_output("vpc_id")
PRIVATE_SUBNET_IDS = VPC.get_output("private_subnet_ids")

provider = k8s.Provider(
    f"{RESOURCE_PREFIX}-{NAME}",
    kubeconfig=KUBECONFIG,
    opts=pulumi.ResourceOptions(parent=CLUSTER),
)

poll_ns = k8s.core.v1.Namespace(
    "poll",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="poll",
    ),
    opts=pulumi.ResourceOptions(provider=provider),
)

subnet_group = aws.rds.SubnetGroup(
    f"{RESOURCE_PREFIX}-{NAME}",
    description=f"ts-demos demo env: Subnet group for poll demp",
    subnet_ids=PRIVATE_SUBNET_IDS,
    tags=TAGS,
)

# get the vpc so we can know the cidr block:
vpc = aws.ec2.get_vpc(id=VPC_ID)

security_group = aws.ec2.SecurityGroup(
    f"{RESOURCE_PREFIX}-{NAME}-db-sg",
    description=f"Security group for poll-demo  database",
    vpc_id=VPC_ID,
    ingress=[
        aws.ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=5432,
            to_port=5432,
            cidr_blocks=[vpc.cidr_block],
        )
    ],
    egress=[
        aws.ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
        )
    ],
    tags=TAGS,
)

db_password = random.RandomPassword(
    f"{RESOURCE_PREFIX}-{NAME}-db-password",
    length=32,
    special=False,
)

db = aws.rds.Instance(
    f"{RESOURCE_PREFIX}-{NAME}-poll",
    db_subnet_group_name=subnet_group.name,
    allocated_storage=20,
    max_allocated_storage=100,
    copy_tags_to_snapshot=True,
    db_name="poll",
    engine="postgres",
    instance_class="db.t4g.micro",
    engine_version="13.13",
    vpc_security_group_ids=[security_group.id],
    username="poll",
    password="correct-horse-battery-stable",
    tags=TAGS,
    skip_final_snapshot=True,
)

pulumi.export("db_host", db.endpoint)

pg_provider = postgresql.Provider("postgres", host=db.endpoint, port=5432, username="poll", password="correct-horse-battery-stable", database="poll")

answers_table = postgresql.Table(
    "poll_answers",
    name="poll_answers",
    schema="public",
    columns=[
        postgresql.TableColumnArgs(
            name="id",
            type="serial",
            primary_key=True,
        ),
        postgresql.TableColumnArgs(
            name="created_at",
            type="timestamp with time zone",
            default="CURRENT_TIMESTAMP",
        ),
        postgresql.TableColumnArgs(
            name="answer",
            type="text",
            nullable=False,
        ),
        postgresql.TableColumnArgs(
            name="tailscale_device",
            type="text",
            nullable=False,
        ),
        postgresql.TableColumnArgs(
            name="tailscale_user",
            type="text",
            nullable=False,
        ),
    ],
    opts=pulumi.ResourceOptions(provider=pg_provider),
)

created_at_index = postgresql.Index(
    "idx_poll_answers_created_at",
    name="idx_poll_answers_created_at",
    table=answers_table.name,
    columns=["created_at"],
    unique=False,
    opts=pulumi.ResourceOptions(provider=pg_provider),
)

db_secret = k8s.core.v1.Secret(
    "poll-db-secret",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="poll-db-secret",
        namespace=poll_ns.metadata.name,
    ),
    string_data={
        "DATABASE_URL": pulumi.Output.concat(
            "postgresql://",
            "poll",
            ":",
            "correct-horse-battery-stable",
            "@",
            db.endpoint,
            "/",
            "poll"
        ),
    },
    opts=pulumi.ResourceOptions(provider=provider, parent=poll_ns),
)

sa = k8s.core.v1.ServiceAccount(
    "poll",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=poll_ns.metadata.name,
    ),
    opts=pulumi.ResourceOptions(provider=provider, parent=poll_ns),
)

# Ensure the necessary permissions to access the secret
role = k8s.rbac.v1.Role(
    "poll",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=poll_ns.metadata.name,
    ),
    rules=[
        k8s.rbac.v1.PolicyRuleArgs(
            api_groups=[""],
            resources=["secrets"],
            verbs=["get", "create", "update"],
        ),
    ],
    opts=pulumi.ResourceOptions(provider=provider, parent=poll_ns),
)

rolebinding = k8s.rbac.v1.RoleBinding(
    "poll",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=poll_ns.metadata.name,
    ),
    role_ref=k8s.rbac.v1.RoleRefArgs(
        api_group="rbac.authorization.k8s.io",
        kind="Role",
        name=role.metadata.name,
    ),
    subjects=[
        k8s.rbac.v1.SubjectArgs(
            kind="ServiceAccount",
            name=sa.metadata.name,
            namespace=poll_ns.metadata.name,
        ),
    ],
    opts=pulumi.ResourceOptions(provider=provider, parent=poll_ns),
)

deployment = k8s.apps.v1.Deployment(
    "poll",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        namespace=poll_ns.metadata.name,
    ),
    spec=k8s.apps.v1.DeploymentSpecArgs(
        replicas=1,
        selector=k8s.meta.v1.LabelSelectorArgs(
            match_labels=LABELS,
        ),
        template=k8s.core.v1.PodTemplateSpecArgs(
            metadata=k8s.meta.v1.ObjectMetaArgs(
                labels=LABELS,
            ),
            spec=k8s.core.v1.PodSpecArgs(
                service_account_name=sa.metadata.name,
                containers=[
                    k8s.core.v1.ContainerArgs(
                        name="poll",
                        ports=[k8s.core.v1.ContainerPortArgs(container_port=8080)],
                        image="ghcr.io/tailscale-dev/poll-demo:latest",
                        image_pull_policy="Always",
                        env=[
                            k8s.core.v1.EnvVarArgs(
                                name="DATABASE_URL",
                                value_from=k8s.core.v1.EnvVarSourceArgs(
                                    secret_key_ref=k8s.core.v1.SecretKeySelectorArgs(
                                        name=db_secret.metadata.name,
                                        key="DATABASE_URL",
                                    )
                                ),
                            ),
                            k8s.core.v1.EnvVarArgs(
                                name="TS_AUTHKEY",
                                value="tskey-auth-kKjQ6DieW511CNTRL-jBLH3iwJXQVikfPoSuRLQV7Q5EDepfaQ"
                            ),
                            k8s.core.v1.EnvVarArgs(
                                name="TS_STATE_DIR",
                                value="kube:poll-state"
                            )
                        ]
                    ),
                ],
            ),
        ),
    ),
    opts=pulumi.ResourceOptions(provider=provider, parent=poll_ns),
)

