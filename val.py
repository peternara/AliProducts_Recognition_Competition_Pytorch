# Author: Jingxiao Gu
# Description: Val Code for AliProducts Recognition Competition

import time
from reader.dataloader import *
from utils.metric import *
from utils.margin import *
from model import modelzoo
from utils.loss import *
from pytorch_metric_learning import losses, miners
from apex import amp

def val(val_loader: Any, model: Any, margin: Any, criterion: Any, num_classes: Any) -> None:
    batch_time = AverageMeter()
    losses = AverageMeter()
    avg_score = AverageMeter()
    map_score = MapAverageMeter(num_classes)

    model.eval()
    num_steps = len(val_loader)

    print('val total batches: {}'.format(num_steps))
    end = time.time()

    with torch.no_grad():
        for i, (input_, target, img_name) in enumerate(val_loader):
            if i >= num_steps:
                break

            output = model(input_.cuda())
            output = margin(output, target.cuda())

            loss = criterion(output, target.cuda())
            confs, predicts = torch.max(output.detach(), dim=1)
            avg_score.update(GAP(predicts, confs, target))

            pred_list, true_list = MAP(predicts, confs, target, num_classes)
            map_score.update(pred_list, true_list)

            losses.update(loss.data.item(), input_.size(0))

            batch_time.update(time.time() - end)
            end = time.time()

            if i % LOG_FREQ == 0:
                print('[{}/{}]\t time {:.3f} ({:.3f})\t loss {:.4f} ({:.4f})\t GAP {:.4f} ({:.4f})\t MAP: {:.4f}\t'.format(
                    i, num_steps, batch_time.val, batch_time.avg, losses.val, losses.avg, avg_score.val, avg_score.avg, map_score.avg_map))

    print(' * on val, average GAP:{:.4f}\t MAP:{:.4f}\t MEAN ERROR:{:.4f}'.format(avg_score.avg, map_score.avg_map, map_score.error))

    if GENERATE_SELECT == True:
        class_ids = []
        confidence = []
        for index in range(len(map_score.simple_map)):
            class_ids.append(index)
            confidence.append(map_score.simple_map[index])
        good_data = {'class_id': class_ids, 'confidence':confidence}
        data_df = pd.DataFrame(good_data)
        data_df.to_csv(SELECT_CLASS, index=False, header=True)

if __name__ == '__main__':
    global_start_time = time.time()
    train_loader, val_loader, label_encoder_train, label_encoder_val, num_classes = load_data('val')
    # single GPU: [0]; Multi GPU: [0, 1, ...]
    device_ids = DEVICE_ID

    # Backbone
    # TODO: Add more backbones
    model = modelzoo.get_model(BACKBONE, num_classes)
    print('Backbone: {}'.format(BACKBONE))

    # Change last two layers to adapt for the dataset and classification
    # This configuration only for resnet, other models should be different
    model.avg_pool = nn.AdaptiveAvgPool2d(1)

    if BACKBONE == 'resnet34':
        in_feature = 512
    else:
        in_feature = 2048

    if MARGIN_TYPE == 'arcMargin':
        margin = losses.ArcFaceLoss
        # margin = ArcMarginProduct(in_feature, num_classes)
    elif MARGIN_TYPE == 'inner':
        margin = InnerProduct(in_feature, num_classes)
    elif MARGIN_TYPE == 'tripletMargin':
        margin = losses.TripletMarginLoss(margin=0.1)

    # Make model in device 0
    # Set parallel. Single GPU is also okay.
    model.cuda(device_ids[0])
    margin.cuda(device_ids[0])

    if MIXED_PRECISION_TRAIN == True:
        [model, margin]= amp.initialize([model, margin], opt_level="O1")

    model = nn.DataParallel(model, device_ids=device_ids)
    margin = nn.DataParallel(margin, device_ids=device_ids)

    # if checkpoint is not none, load it as pretrained
    if BACKBONE_CHECKPOINT != '':
        checkpoint = torch.load(BACKBONE_CHECKPOINT)
        model.load_state_dict(checkpoint, strict=False)

    if MARGIN_CHECKPOINT != '':
        checkpoint = torch.load(MARGIN_CHECKPOINT)
        margin.load_state_dict(checkpoint, strict=False)

    # Loss function
    # TODO: Add more loss function
    if LOSS_FUNC == 'focalLoss':
        criterion = FocalLoss()
    else:
        criterion = CELoss()

    val(val_loader, model, margin, criterion, num_classes)
