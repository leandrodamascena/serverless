from aws_cdk import (
    core, aws_dynamodb as dynamodb, aws_iam as iam, aws_apigateway as apigateway,
)

from aws_cdk.custom_resources import (
    AwsSdkCall, AwsCustomResource, AwsCustomResourcePolicy, PhysicalResourceId
)

DEFAULT_CONF = {
    "table_name": "atomicCounter",
    "incremental_count": 1
}

class TheDynamodbAtomicCounterStack(core.Stack):

    def __init__(self, scope: core.Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # IAM Role for APIGateway
        iam_role = iam.Role(scope=self, id="iam-role-apigw", 
            role_name="iam-role-apigw",
            assumed_by=iam.ServicePrincipal("apigateway.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonDynamoDBFullAccess"),],
            path="/service-role/"
        )

        # IAM Role for PopulateData
        iam_role_lambda = iam.Role(scope=self, id="iam-role-lambda", 
            role_name="iam-role-lambda",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonDynamoDBFullAccess"),],
            path="/service-role/"
        )

        """
        1: Creating the DynamoDB table with a Partition (PrimaryKey)
        """
        partition_key = dynamodb.Attribute(name="atomicCounter", type=dynamodb.AttributeType.STRING)
        dynamodb_table = dynamodb.Table(scope=self, id="dynamodb-table",
            table_name=DEFAULT_CONF.get("table_name"),
            partition_key=partition_key,
            removal_policy=core.RemovalPolicy.DESTROY
        )

        """
        2: We must insert initial data into DynamoDB table
        """
        custom_policy = AwsCustomResourcePolicy.from_sdk_calls(resources=AwsCustomResourcePolicy.ANY_RESOURCE)

        # Params for insert
        create_params = {
            "TableName": DEFAULT_CONF.get("table_name"),
            "Item": {
                "atomicCounter": {
                    "S": "id"
                },
                "counterValue": {
                    "N": "1"
                }
            },
            "ConditionExpression": "attribute_not_exists(atomicCounter)"
        }

        # AwsSdkCall for putItem operation
        # https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.custom_resources/AwsSdkCall.html
        data_table = AwsSdkCall(
            service="DynamoDB",
            action="putItem",
            api_version=None,
            physical_resource_id=PhysicalResourceId.of("data-table"),
            parameters=create_params
        )

        # AwsCustomResource for putItemoperation
        # https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.custom_resources/AwsCustomResource.html
        data_resource = AwsCustomResource(scope=self, id="custom-populate-ddb",
            policy=custom_policy,
            log_retention=None,
            role=iam_role_lambda,
            on_create=data_table,
            on_update=data_table
        )
        data_resource.node.add_dependency(dynamodb_table)
        

        """
        3: Creating Rest API Gateway
        """
        api_gateway_atomic = apigateway.RestApi(scope=self, id="atomic-counter-api",
            rest_api_name="Atomic Count API",
            description="This API serve an Atomic Count API pattern.",
            endpoint_export_name="counter",
            endpoint_types=[apigateway.EndpointType.REGIONAL],
            deploy=True
        )

        """
        4: Creating Models for Sucess and Error
        
        success_response_model = api_gateway_atomic.add_model(
            id="EmptyModel",
            content_type="application/json",
            model_name="EmptyModel",
            schema=apigateway.JsonSchema(
                schema=apigateway.JsonSchemaVersion.DRAFT4,
                title="Success Schema",
                type=apigateway.JsonSchemaType.OBJECT
            )
        )

        error_response_model = api_gateway_atomic.add_model(
            id="ErrorModel",
            content_type="application/json",
            model_name="ErrorModel",
            schema=apigateway.JsonSchema(
                schema=apigateway.JsonSchemaVersion.DRAFT4,
                title="Error Schema",
                type=apigateway.JsonSchemaType.OBJECT,
                properties={
                    "message": apigateway.JsonSchema(
                        type=apigateway.JsonSchemaType.STRING
                    )
                }
            )
        )
        """

        """ 
        5: Creating AWS Integration Service Response, Integration Options and Integration Service Method
        """
        # 4.1: Integration Service Response
        integration_response_aws_service_integration = apigateway.IntegrationResponse(
            status_code="200",
            response_templates={
                "application/json": "#set($value = $input.json('Attributes.counterValue.N'))\r\n#set($l = $value.length())\r\n#set($l = $l - 1)\r\n$value.substring(1,$l)"
            }
        )

        # 4.2: Integration Options
        options_api_aws_service_integration = apigateway.IntegrationOptions(
            credentials_role=iam_role,
            integration_responses=[integration_response_aws_service_integration],
            passthrough_behavior=apigateway.PassthroughBehavior.NEVER,
            request_templates={
                "application/json": "{\r\n    \"TableName\": \"atomicCounter\",\r\n    \"Key\": {\r\n        \"atomicCounter\": {\r\n            \"S\": \"id\"\r\n        }\r\n    },\r\n    \"UpdateExpression\": \"set counterValue = counterValue + :num\",\r\n    \"ExpressionAttributeValues\": {\r\n        \":num\": {\"N\": \"1\"}\r\n    },\r\n    \"ReturnValues\" : \"UPDATED_OLD\"\r\n}"
            }
        )

        # 4.3: Integration Service Method
        api_aws_service_integration = apigateway.AwsIntegration( 
            service="dynamodb",
            action="UpdateItem",
            integration_http_method="POST",
            options=options_api_aws_service_integration
        )

        """
        5: Adding resource /counter and method GET.
        """
        method_api_gateway_atomic = api_gateway_atomic.root.add_resource('counter')

        method_api_gateway_atomic.add_method("GET", api_aws_service_integration,
            method_responses=[{
                "statusCode": "200",
                "responseModels": {
                    "application/json": apigateway.Model.EMPTY_MODEL
                }
            }]
        )

        """
        6: Output URL
        The output url will be: https://xxx.execute-api.REGION.amazonaws.com/prod/counter
        """
        core.CfnOutput(scope=self, id="apigw-counter-url", 
            value=f'{api_gateway_atomic.url}counter'
        )