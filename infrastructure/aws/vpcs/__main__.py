from typing import Dict
import pulumi
import pulumi_aws as aws
import pulumi_awsx as awsx
import lbrlabs_pulumi_tailscalebastion as ts

PROJECT_NAME = pulumi.get_project()
STACK = pulumi.get_stack()

AWS_CONFIG = pulumi.Config("aws")
REGION = AWS_CONFIG.require("region")
NAME = "-".join(REGION.split("-")[:2])
CONFIG = pulumi.Config()
CIDR_BLOCK = CONFIG.require("cidr_block")

PULUMI_CONFIG = pulumi.Config("pulumi")
RESOURCE_PREFIX = PULUMI_CONFIG.require("resourcePrefix")


ENABLE_APP_CONNECTOR = CONFIG.get_bool("enable_app_connector", default=False)
ENABLE_EXIT_NODE = CONFIG.get_bool("enable_exit_node", default=False)

TAGS = {
    "environment": STACK,
    "project": PROJECT_NAME,
    "owner": "lbriggs",
    "deployed_by": "pulumi",
    "org": "lbrlabs",
}

CONFIG = pulumi.Config()

vpc = awsx.ec2.Vpc(
    f"{RESOURCE_PREFIX}-vpc-{NAME}",
    cidr_block=CIDR_BLOCK,
    subnet_strategy="Auto",
    subnet_specs=[
        awsx.ec2.SubnetSpecArgs(
            type=awsx.ec2.SubnetType.PUBLIC,
            cidr_mask=20,
            tags={"kubernetes.io/role/elb": "1", **TAGS},
        ),
        awsx.ec2.SubnetSpecArgs(
            type=awsx.ec2.SubnetType.PRIVATE,
            cidr_mask=19,
            tags={"kubernetes.io/role/internal-elb": "1", **TAGS},
        ),
    ],
    enable_dns_hostnames=True,
    enable_dns_support=True,
    number_of_availability_zones=2,
    nat_gateways=awsx.ec2.NatGatewayConfigurationArgs(
        strategy=awsx.ec2.NatGatewayStrategy.ONE_PER_AZ
    ),
    tags=TAGS,
)


bastion = ts.aws.Bastion(
    f"{RESOURCE_PREFIX}-subnet-router-{NAME}",
    vpc_id=vpc.vpc_id,
    subnet_ids=vpc.public_subnet_ids,
    region=REGION,
    routes=[CIDR_BLOCK],
    high_availability=True,
    public=True,
    enable_ssh=True,
    enable_exit_node=False,
    tailscale_tags=[f"tag:{STACK}", "tag:subnet-router"],
    opts=pulumi.ResourceOptions(parent=vpc),
)

if ENABLE_APP_CONNECTOR:

    connector = ts.aws.Bastion(
        f"{RESOURCE_PREFIX}-app-connector-{NAME}",
        vpc_id=vpc.vpc_id,
        subnet_ids=vpc.private_subnet_ids,
        region=REGION,
        high_availability=False,
        public=False,
        enable_app_connector=True,
        tailscale_tags=[f"tag:{STACK}", "tag:appconnector"],
        opts=pulumi.ResourceOptions(parent=vpc),
    )

if ENABLE_EXIT_NODE:

    exitNode = ts.aws.Bastion(
        f"{RESOURCE_PREFIX}-exitnode-{NAME}",
        vpc_id=vpc.vpc_id,
        subnet_ids=vpc.private_subnet_ids,
        region=REGION,
        high_availability=False,
        public=False,
        enable_exit_node=True,
        tailscale_tags=["tag:exit-node", f"tag:{STACK}"],
        opts=pulumi.ResourceOptions(parent=vpc),
    )

pulumi.export(f"vpc_id", vpc.vpc_id)
pulumi.export(f"public_subnet_ids", vpc.public_subnet_ids)
pulumi.export(f"private_subnet_ids", vpc.private_subnet_ids)
