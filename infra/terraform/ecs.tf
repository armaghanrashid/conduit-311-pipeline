resource "aws_ecs_cluster" "conduit" {
  name = "${var.name_prefix}-311"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "conduit" {
  name              = "/ecs/${var.name_prefix}-311"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_task_definition" "conduit" {
  family                   = "${var.name_prefix}-311"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    cpu_architecture        = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "conduit"
      image     = "${aws_ecr_repository.conduit.repository_url}:${var.image_tag}"
      essential = true
      command   = ["run", "--source", "api", "--limit", "50000", "--lookback-days", "7"]

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.conduit.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "conduit"
        }
      }
    }
  ])
}

resource "aws_cloudwatch_event_rule" "nightly" {
  name                = "${var.name_prefix}-311-nightly"
  description         = "Run the conduit batch pipeline on a schedule."
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "nightly" {
  rule      = aws_cloudwatch_event_rule.nightly.name
  target_id = "conduit-task"
  arn       = aws_ecs_cluster.conduit.arn
  role_arn  = aws_iam_role.events.arn

  ecs_target {
    launch_type         = "FARGATE"
    task_count          = 1
    task_definition_arn = aws_ecs_task_definition.conduit.arn

    network_configuration {
      subnets          = var.subnet_ids
      security_groups  = var.security_group_ids
      assign_public_ip = var.assign_public_ip
    }
  }
}
